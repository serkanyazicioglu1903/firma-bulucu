"""Fail-closed, company-scoped customer/contact READ for signed review mode.

No legacy unscoped CRM queries, demo data, automatic migrations or writes.
CRM is not yet company-owned in the live ct_app schema, so this adapter
returns NOT_READY until exact direct, non-null ownership and a validated
composite customer/contact company FK exist. Access is DB-grant-checked on
every call; caller supplies a separately server-verified signed principal.

This code does NOT certify future production multi-company authorization.
"""
from scripts.group_company_catalog import COMPANY_LABELS
from scripts.postgres_connection import sslmode_for
from scripts.postgres_scoped_company_read import (
    PRINCIPAL_PATTERN, LIMIT, authorize_company_on_cursor,
)
from scripts.staging_transaction_smoke import validate_test_url

# Exactly two defensible starting points for per-company CRM. In particular,
# opportunity.customer_id is nullable, so inherited ownership is NOT assumed.
CRM_READ_SECTIONS = {
    "Müşteriler": (
        "customers",
        ("id", "name", "country", "sector", "status", "owner", "currency"),
    ),
    "İrtibat Kişileri": (
        "contacts",
        ("id", "customer_id", "name", "title", "department", "email", "phone"),
    ),
}
REQUIRED_CRM_OWNERS = ("customers", "contacts")


def _valid_request(principal_id, company_code, section):
    return (
        isinstance(principal_id, str)
        and PRINCIPAL_PATTERN.fullmatch(principal_id) is not None
        and isinstance(company_code, str) and company_code in COMPANY_LABELS
        and isinstance(section, str) and section in CRM_READ_SECTIONS
    )


def company_crm_structure_ready_on_cursor(cur):
    """Metadata-only: both tables owned, and contacts cannot cross companies.

    Owner columns need NOT NULL. The contacts(customer_id,legal_entity_id)
    composite FK -> customers(id,legal_entity_id) must exist and be VALIDATED.
    A legacy single-field customer_id FK is insufficient protection.
    """
    cur.execute(
        "SELECT c.table_name FROM information_schema.columns c "
        "WHERE c.table_schema='ct_app' AND c.table_name = ANY(%s) "
        "AND c.column_name='legal_entity_id' AND c.is_nullable='NO'",
        (list(REQUIRED_CRM_OWNERS),),
    )
    fields = [row[0] for row in cur.fetchall()]
    if len(fields) != len(REQUIRED_CRM_OWNERS) or set(fields) != set(REQUIRED_CRM_OWNERS):
        return False
    cur.execute(
        "SELECT EXISTS (SELECT 1 FROM pg_constraint f "
        "WHERE f.contype='f' AND f.convalidated "
        "AND f.conrelid=to_regclass('ct_app.contacts') "
        "AND f.confrelid=to_regclass('ct_app.customers') "
        "AND f.conkey = ARRAY["
        "(SELECT a.attnum FROM pg_attribute a WHERE "
        "a.attrelid=to_regclass('ct_app.contacts') AND a.attname='customer_id' "
        "AND a.attnum>0 AND NOT a.attisdropped),"
        "(SELECT a.attnum FROM pg_attribute a WHERE "
        "a.attrelid=to_regclass('ct_app.contacts') AND a.attname='legal_entity_id' "
        "AND a.attnum>0 AND NOT a.attisdropped)]::smallint[] "
        "AND f.confkey = ARRAY["
        "(SELECT a.attnum FROM pg_attribute a WHERE "
        "a.attrelid=to_regclass('ct_app.customers') AND a.attname='id' "
        "AND a.attnum>0 AND NOT a.attisdropped),"
        "(SELECT a.attnum FROM pg_attribute a WHERE "
        "a.attrelid=to_regclass('ct_app.customers') AND a.attname='legal_entity_id' "
        "AND a.attnum>0 AND NOT a.attisdropped)]::smallint[])"
    )
    result = cur.fetchone()
    return result is not None and result[0] is True


def read_company_crm_on_cursor(cur, principal_id, company_code, section):
    """Returns (status, rows), no data if a prerequisite is missing."""
    if not _valid_request(principal_id, company_code, section):
        return "forbidden", []
    status, company_id = authorize_company_on_cursor(
        cur, principal_id, company_code
    )
    if status != "ok":
        return status, []
    if not company_crm_structure_ready_on_cursor(cur):
        return "not_ready", []

    table, columns = CRM_READ_SECTIONS[section]
    fixed_columns = ", ".join('b."' + name + '"' for name in columns)
    parent = (
        'JOIN "ct_app"."customers" p '
        'ON p.id=b.customer_id AND p.legal_entity_id=b.legal_entity_id '
        if section == "İrtibat Kişileri" else ""
    )
    # IDs, SQL identifiers and columns are drawn only from compile-time data;
    # principal_id and legal company code are always bound SQL parameters.
    query = (
        'SELECT ' + fixed_columns + ' FROM "ct_app"."' + table + '" b '
        + parent
        + 'JOIN "ct_app"."legal_entities" e ON e.id=b.legal_entity_id '
        'JOIN "ct_app"."company_read_grants" g ON g.legal_entity_id=e.id '
        'WHERE b.legal_entity_id=%s AND e.code=%s AND e.active=TRUE '
        'AND g.principal_id=%s AND g.can_read=TRUE '
        'ORDER BY b.id DESC LIMIT ' + str(LIMIT)
    )
    cur.execute(query, (company_id, company_code, principal_id))
    records = cur.fetchall()
    if records and isinstance(records[0], dict):
        return "ok", [dict(row) for row in records]
    return "ok", [dict(zip(columns, row)) for row in records]


def read_company_crm(url, principal_id, company_code, section):
    """Read only through a repeatable, authenticated, company-granted snapshot.

    Streamlit user authentication/signature must happen BEFORE calling this
    adapter; company selection alone must never determine authorisation.
    """
    if not _valid_request(principal_id, company_code, section):
        return "forbidden", []
    if not validate_test_url(url):
        return "invalid_url", []
    try:
        import psycopg
        with psycopg.connect(
            str(url).strip(), connect_timeout=8,
            sslmode=sslmode_for(url), autocommit=True,
        ) as conn:
            with conn.transaction():
                with conn.cursor() as cur:
                    cur.execute(
                        "SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY"
                    )
                    cur.execute("SET LOCAL statement_timeout = '15s'")
                    cur.execute("SET LOCAL lock_timeout = '3s'")
                    return read_company_crm_on_cursor(
                        cur, principal_id, company_code, section
                    )
    except Exception:
        # Exception text can contain confidential company data or DB secrets.
        return "failed", []
