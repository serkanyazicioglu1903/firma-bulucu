"""Per-company operations and financial overview: exact grant-scoped aggregates.

NOT an intercompany consolidation or production-ready management report.
Returns one independently authorized legal entity only. All amounts remain
separate by source currency; conversion, tax and elimination are forbidden.
No shared CRM/customer/product data are exposed.
"""
from scripts.group_company_catalog import COMPANY_LABELS
from scripts.postgres_company_scope import CRITICAL_TABLES
from scripts.postgres_connection import sslmode_for
from scripts.staging_transaction_smoke import validate_test_url
from scripts.postgres_scoped_company_read import (
    OWNED_READ_SECTIONS,
    authorize_company_on_cursor,
)

COUNTS = tuple(CRITICAL_TABLES)
assert set(COUNTS) == {item[0] for item in OWNED_READ_SECTIONS.values()}

# Only vetted compile-time constants; not user-controlled SQL identifiers.
FINANCE_AGGREGATES = (
    ("cash", "cash_accounts", "balance", None),
    ("receivables_open", "receivables", "amount - paid_amount", "status"),
    ("payables_open", "payables", "amount - paid_amount", "status"),
)
assert len(FINANCE_AGGREGATES) == 3


def _grant_filter():
    return (
        ' JOIN "ct_app"."legal_entities" e ON e.id=b.legal_entity_id '
        'JOIN "ct_app"."company_read_grants" g ON g.legal_entity_id=e.id '
        'WHERE b.legal_entity_id=%s AND e.code=%s AND e.active=TRUE '
        'AND g.principal_id=%s AND g.can_read=TRUE'
    )


def _aggregate_rows(cur, company_id, company_code, principal_id):
    params = (company_id, company_code, principal_id)
    result = {}
    for table in COUNTS:
        query = (
            'SELECT COUNT(*) FROM "ct_app"."' + table + '" b '
            + _grant_filter()
        )
        cur.execute(query, params)
        result[table] = int(cur.fetchone()[0])

    finance = {}
    for name, table, expression, status_column in FINANCE_AGGREGATES:
        qualifier = (
            " AND COALESCE(b.status, '') <> 'İptal'"
            if status_column else ""
        )
        # Do not SUM EUR, TRY, USD or GBP together; separate each currency.
        query = (
            'SELECT b.currency, COALESCE(SUM(b.' +
            expression.replace(" - ", " - b.") +
            '), 0) FROM "ct_app"."' + table + '" b '
            + _grant_filter() + qualifier +
            ' GROUP BY b.currency ORDER BY b.currency'
        )
        cur.execute(query, params)
        currency_rows = cur.fetchall()
        finance[name] = tuple({
            "currency": currency,
            "amount": amount,
        } for currency, amount in currency_rows)
    cur.execute(
        'SELECT COALESCE(SUM(b.quantity_available_kg), 0), '
        'COALESCE(SUM(b.quality_hold_kg), 0) '
        'FROM "ct_app"."inventory_lots" b '
        + _grant_filter(),
        params,
    )
    available_kg, held_kg = cur.fetchone()
    result["inventory_quantity_kg"] = available_kg
    result["quality_hold_kg"] = held_kg
    return {
        "status": "ok",
        "company_code": company_code,
        "counts": result,
        "finance_by_currency": finance,
        "consolidation_verified": False,
        "cross_company_totals": False,
    }


def company_executive_snapshot_on_cursor(cur, principal_id, company_code):
    """Fail closed before aggregate SELECTs for unknown/revoked company."""
    if not isinstance(company_code, str) or company_code not in COMPANY_LABELS:
        return "forbidden", {}
    status, company_id = authorize_company_on_cursor(
        cur, principal_id, company_code
    )
    if status != "ok":
        return status, {}
    return "ok", _aggregate_rows(
        cur, company_id, company_code, principal_id
    )


def read_company_executive_snapshot(url, principal_id, company_code):
    """Never cache results or return raw PostgreSQL errors."""
    if not isinstance(company_code, str) or company_code not in COMPANY_LABELS:
        return "forbidden", {}
    if not validate_test_url(url):
        return "invalid_url", {}
    try:
        import psycopg
        with psycopg.connect(
            str(url).strip(), connect_timeout=8, sslmode=sslmode_for(url),
            autocommit=True,
        ) as conn:
            with conn.transaction():
                with conn.cursor() as cur:
                    cur.execute(
                        "SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY"
                    )
                    cur.execute("SET LOCAL statement_timeout = '15s'")
                    cur.execute("SET LOCAL lock_timeout = '3s'")
                    return company_executive_snapshot_on_cursor(
                        cur, principal_id, company_code
                    )
    except Exception:
        return "failed", {}
