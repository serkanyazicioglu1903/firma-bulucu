"""Read-only, automatic legacy UI guard for beginning four-company migrations.

Do not permit ownerless legacy CRM/stock/finance forms once ANY sign of the
legal-entity migration is visible. Does not assign ownership or authorize
production. Existing ownerless ct_app remains on its unchanged legacy path.

The check is performed on every authenticated Control Tower render in live
PostgreSQL mode, WITHOUT caching. Metadata failures fail closed. An explicit
signed company-scoped review mode is handled separately by the UI.
"""
from scripts.postgres_company_scope import CRITICAL_TABLES
from scripts.postgres_connection import sslmode_for
from scripts.staging_transaction_smoke import validate_test_url

ALLOWED_TABLES = frozenset(CRITICAL_TABLES)
assert len(ALLOWED_TABLES) == 8


def classify_schema_metadata(table_rows, owner_rows, markers):
    """Return a conservative non-success status from catalog-only results.

    Only a complete pre-migration 8-table schema with no owner columns and no
    legal-entity registry is allowed to retain existing single-company UI.
    """
    if not isinstance(table_rows, (tuple, list)) or not isinstance(owner_rows, (tuple, list)):
        return "metadata_unavailable"
    if not isinstance(markers, (tuple, list)) or len(markers) != 5:
        return "metadata_unavailable"
    if any(type(value) is not bool for value in markers):
        return "metadata_unavailable"
    if len(table_rows) != len(ALLOWED_TABLES) or set(table_rows) != ALLOWED_TABLES:
        return "metadata_unavailable"
    if (len(owner_rows) != len(set(owner_rows))
            or any(not isinstance(value, str) or value not in ALLOWED_TABLES
                   for value in owner_rows)):
        return "metadata_unavailable"
    if len(owner_rows) == 0 and not any(markers):
        return "legacy_schema_only"
    if len(owner_rows) == len(ALLOWED_TABLES) and all(markers):
        return "company_schema_present"
    return "partial_company_schema"


def company_schema_status_on_cursor(cur):
    """Read metadata only; never query application data or mutate tables.

    Caller must own a read-only consistent database transaction.
    """
    cur.execute(
        "SELECT c.relname FROM pg_class c "
        "JOIN pg_namespace n ON n.oid=c.relnamespace "
        "WHERE n.nspname='ct_app' AND c.relkind IN ('r','p') "
        "AND c.relname = ANY(%s) ORDER BY c.relname",
        (list(CRITICAL_TABLES),),
    )
    table_rows = [row[0] for row in cur.fetchall()]
    cur.execute(
        "SELECT c.relname FROM pg_class c "
        "JOIN pg_namespace n ON n.oid=c.relnamespace "
        "JOIN pg_attribute a ON a.attrelid=c.oid "
        "WHERE n.nspname='ct_app' AND c.relkind IN ('r','p') "
        "AND c.relname = ANY(%s) AND a.attname='legal_entity_id' "
        "AND a.attnum > 0 AND NOT a.attisdropped "
        "ORDER BY c.relname",
        (list(CRITICAL_TABLES),),
    )
    owner_rows = [row[0] for row in cur.fetchall()]
    cur.execute(
        "SELECT to_regclass('ct_app.legal_entities') IS NOT NULL, "
        "to_regclass('ct_app.company_read_grants') IS NOT NULL, "
        "to_regclass('ct_app.company_write_grants') IS NOT NULL, "
        "to_regclass('ct_app.company_warehouse_scope') IS NOT NULL, "
        "to_regclass('ct_app.company_operation_audit') IS NOT NULL"
    )
    markers = cur.fetchone()
    return classify_schema_metadata(table_rows, owner_rows, markers)


def inspect_company_migration_state(url):
    """One read-only call. Distinguishes existing legacy from partial migration.

    status = legacy_schema_only | partial_company_schema |
             company_schema_present | metadata_unavailable.
    The caller must block all three statuses except legacy_schema_only.
    """
    if not validate_test_url(url):
        return "metadata_unavailable"
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
                    cur.execute("SET LOCAL statement_timeout = '10s'")
                    cur.execute("SET LOCAL lock_timeout = '3s'")
                    return company_schema_status_on_cursor(cur)
    except Exception:
        return "metadata_unavailable"
