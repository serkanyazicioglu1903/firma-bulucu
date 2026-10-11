"""Read-only, automatic legacy UI guard for beginning four-company migrations.

Do not permit ownerless legacy CRM/stock/finance forms once ANY sign of the
legal-entity migration is visible. Does not assign ownership or authorize
production. Existing ownerless ct_app remains on its unchanged legacy path.

The check is performed on every authenticated Control Tower render in live
PostgreSQL mode, WITHOUT caching. Metadata failures fail closed. An explicit
signed company-scoped review mode is handled separately by the UI.
"""
from scripts.postgres_company_scope import CRITICAL_TABLES
from scripts.postgres_live_schema import schema_ddl_steps
from scripts.postgres_connection import sslmode_for
from scripts.staging_transaction_smoke import validate_test_url

ALLOWED_TABLES = frozenset(CRITICAL_TABLES)
assert len(ALLOWED_TABLES) == 8

# Old legacy guard only checked eight operational tables and five migration
# markers. Company owners, RLS or direct API grants on the OTHER 18 ct_app
# tables could previously appear while the unscoped UI stayed enabled.
EXPECTED_TABLES = frozenset(schema_ddl_steps()[0])
assert len(EXPECTED_TABLES) == 26 and ALLOWED_TABLES <= EXPECTED_TABLES


def classify_extended_migration_signals(rows):
    """Metadata-only all-26 gate: None on incomplete/invalid catalog input.

    Row: (table, has_legal_entity_id, rls_enabled, force_rls,
          has_policy, api_role_effective_grant).
    Any migration/security signal blocks legacy unscoped operations. A
    configured API grant is NOT proof of internet exposure; it requires review.
    """
    if not isinstance(rows, (tuple, list)) or len(rows) != len(EXPECTED_TABLES):
        return None
    seen = set()
    has_signal = False
    for row in rows:
        if (not isinstance(row, (tuple, list)) or len(row) != 6
                or not isinstance(row[0], str)
                or row[0] not in EXPECTED_TABLES or row[0] in seen
                or any(type(flag) is not bool for flag in row[1:])):
            return None
        seen.add(row[0])
        has_signal = has_signal or any(row[1:])
    if seen != EXPECTED_TABLES:
        return None
    return has_signal


def extended_migration_signals_on_cursor(cur):
    """Read all ct_app table security metadata; no customer/business rows."""
    cur.execute(
        "SELECT c.relname, (a.attnum IS NOT NULL) AS has_company_owner, "
        "c.relrowsecurity, c.relforcerowsecurity, "
        "EXISTS (SELECT 1 FROM pg_policy p WHERE p.polrelid=c.oid), "
        "EXISTS (SELECT 1 FROM pg_roles r "
        "WHERE r.rolname IN ('anon','authenticated','service_role') "
        "AND has_schema_privilege(r.oid,n.oid,'USAGE') AND ("
        "has_table_privilege(r.oid,c.oid,'SELECT') OR "
        "has_table_privilege(r.oid,c.oid,'INSERT') OR "
        "has_table_privilege(r.oid,c.oid,'UPDATE') OR "
        "has_table_privilege(r.oid,c.oid,'DELETE'))) "
        "FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace "
        "LEFT JOIN pg_attribute a ON a.attrelid=c.oid "
        "AND a.attname='legal_entity_id' AND a.attnum>0 AND NOT a.attisdropped "
        "WHERE n.nspname='ct_app' AND c.relkind IN ('r','p') "
        "ORDER BY c.relname"
    )
    return classify_extended_migration_signals(cur.fetchall())


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
    status = classify_schema_metadata(table_rows, owner_rows, markers)
    # A company migration already blocks the legacy UI. Only the otherwise
    # accepted legacy route needs the stronger 26-table recheck.
    if status != "legacy_schema_only":
        return status
    extended = extended_migration_signals_on_cursor(cur)
    if extended is None:
        return "metadata_unavailable"
    return "partial_company_schema" if extended else "legacy_schema_only"


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
