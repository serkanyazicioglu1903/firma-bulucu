"""Company-scoped READ-ONLY PostgreSQL adapter, NOT connected to Streamlit yet.

This is an isolated migration rehearsal and a proposed future server-side data
access path. Existing UI/API/legacy SQL still lack entity isolation. NEVER
present this module as proof that multi-company production is approved.

The caller must authenticate users independently and supply an immutable,
server-derived principal ID; NEVER pass user-editable IDs, company grants or
queries directly from phone controls. DB grants are verified for every read.
"""
import re

from scripts.group_company_catalog import COMPANY_LABELS
from scripts.postgres_company_scope import CRITICAL_TABLES
from scripts.postgres_connection import sslmode_for
from scripts.staging_transaction_smoke import validate_test_url


# No user-controlled table or column names are ever interpolated.
# Shared, ownerless masters (customers/products) are intentionally excluded.
OWNED_READ_SECTIONS = {
    "Satın Alma": ("purchase_orders",
                  ("id", "po_number", "supplier", "product_name",
                   "quantity_kg", "unit_price", "currency", "status")),
    "Sevkiyat": ("shipments",
                ("id", "purchase_order_id", "shipment_ref", "quantity_kg", "status")),
    "Stok": ("inventory_lots",
             ("id", "product_name", "lot_number", "quantity_available_kg",
              "quantity_reserved_kg", "currency")),
    "Kalite": ("quality_cases",
               ("id", "case_no", "product_name", "status",
                "affected_quantity_kg", "currency")),
    "Alacaklar": ("receivables",
                  ("id", "customer_id", "amount", "paid_amount",
                   "currency", "status")),
    "Borçlar": ("payables",
                ("id", "supplier", "invoice_no", "amount",
                 "paid_amount", "currency", "status")),
    "Banka / Kasa": ("cash_accounts",
                     ("id", "name", "currency", "balance", "active")),
    "Finans Hareketleri": ("finance_transactions",
                          ("id", "transaction_type", "transaction_date",
                           "amount", "currency", "reference")),
}
assert {table for table, _ in OWNED_READ_SECTIONS.values()} == set(CRITICAL_TABLES)

PRINCIPAL_PATTERN = re.compile(r"^[A-Za-z0-9._@-]{1,128}$")
LIMIT = 100


def grant_table_rehearsal_ddl():
    """Offline-only SQL plan; NEVER applies DDL or seeds a real user.

    No default access; only a separately authenticated administrator can
    authorize future rows after permission and identity review.
    """
    return (
        'CREATE TABLE "ct_app"."company_read_grants" ('
        'principal_id TEXT NOT NULL, '
        'legal_entity_id BIGINT NOT NULL REFERENCES "ct_app"."legal_entities"(id), '
        'can_read BOOLEAN NOT NULL DEFAULT FALSE, '
        'PRIMARY KEY (principal_id, legal_entity_id), '
        'CONSTRAINT company_read_grants_principal_nonempty '
        'CHECK (length(btrim(principal_id)) BETWEEN 1 AND 128))',
    )


def _allowed_arguments(principal_id, company_code, section):
    # Even a logged-in ADMIN is not granted all companies implicitly.
    return (isinstance(principal_id, str) and
            bool(PRINCIPAL_PATTERN.fullmatch(principal_id)) and
            isinstance(company_code, str) and company_code in COMPANY_LABELS and
            isinstance(section, str) and section in OWNED_READ_SECTIONS)


def authorize_company_on_cursor(cur, principal_id, company_code):
    """Deny-by-default DB ownership and grant check for all company reads.

    Caller must supply an independently server-verified principal, never a
    user-editable text field. All business queries MUST also repeat the DB
    grant check to reject revocation or owner changes during a read.
    """
    if not _allowed_arguments(principal_id, company_code, "Satın Alma"):
        return "forbidden", None
    cur.execute(
        "SELECT COUNT(*) FROM information_schema.columns "
        "WHERE table_schema='ct_app' AND column_name='legal_entity_id' "
        "AND is_nullable='NO' AND table_name = ANY(%s)",
        (list(CRITICAL_TABLES),),
    )
    if int(cur.fetchone()[0]) != len(CRITICAL_TABLES):
        return "not_ready", None
    cur.execute(
        "SELECT to_regclass('ct_app.legal_entities') IS NOT NULL, "
        "to_regclass('ct_app.company_read_grants') IS NOT NULL"
    )
    if tuple(cur.fetchone()) != (True, True):
        return "not_ready", None
    cur.execute(
        'SELECT e.id FROM "ct_app"."legal_entities" e '
        'JOIN "ct_app"."company_read_grants" g ON g.legal_entity_id=e.id '
        'WHERE e.code=%s AND e.active=TRUE AND '
        'g.principal_id=%s AND g.can_read=TRUE LIMIT 1',
        (company_code, principal_id),
    )
    owned = cur.fetchone()
    if owned is None:
        return "forbidden", None
    return "ok", int(owned[0])


def read_company_records_on_cursor(cur, principal_id, company_code, section):
    """Guard + limited row read INSIDE the caller's read-only transaction.

    The DB grant and matching legal_entity_id are BOTH checked by PostgreSQL,
    not via UI roles or cached selections. Return status, records. The method
    is intentionally not exposed as a Streamlit page or public endpoint.
    """
    if not _allowed_arguments(principal_id, company_code, section):
        return "forbidden", []
    status, company_id = authorize_company_on_cursor(
        cur, principal_id, company_code
    )
    if status != "ok":
        return status, []
    table, columns = OWNED_READ_SECTIONS[section]
    # Quoting only compile-time, fixed SQL identifiers from this module.
    names = ", ".join('b."' + column + '"' for column in columns)
    statement = (
        'SELECT ' + names + ' FROM "ct_app"."' + table + '" b '
        'JOIN "ct_app"."legal_entities" e ON e.id=b.legal_entity_id '
        'JOIN "ct_app"."company_read_grants" g ON g.legal_entity_id=e.id '
        'WHERE e.id=%s AND e.code=%s AND e.active=TRUE AND '
        'g.principal_id=%s AND g.can_read=TRUE '
        'ORDER BY b.id DESC LIMIT ' + str(LIMIT)
    )
    cur.execute(statement, (company_id, company_code, principal_id))
    # Cursor factories in psycopg can be either tuples or dictionaries.
    records = cur.fetchall()
    if records and isinstance(records[0], dict):
        return "ok", [dict(row) for row in records]
    return "ok", [dict(zip(columns, row)) for row in records]


def read_company_records(url, principal_id, company_code, section):
    """Explicit opt-in server-side read. Returns no rows on every failure.

    This method is NOT wired to the current live Streamlit UI. Once connected,
    principal_id must be obtained from authenticated, server-verified identity
    and bound to DB permissions. Only a completed, approved entity migration
    can satisfy the non-null precondition.
    """
    if not _allowed_arguments(principal_id, company_code, section):
        return "forbidden", []
    if not validate_test_url(url):
        return "invalid_url", []
    try:
        import psycopg
        with psycopg.connect(
            str(url).strip(), connect_timeout=8, sslmode=sslmode_for(url),
            autocommit=True,
        ) as conn:
            with conn.transaction():
                with conn.cursor() as cur:
                    cur.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY")
                    cur.execute("SET LOCAL statement_timeout = '15s'")
                    cur.execute("SET LOCAL lock_timeout = '3s'")
                    return read_company_records_on_cursor(
                        cur, principal_id, company_code, section
                    )
    except Exception:
        # Do not return DB exception text; it might contain private values.
        return "failed", []
