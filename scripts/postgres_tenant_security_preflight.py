"""Read-only tenant-security inventory for an AS Control Tower cutover.

Unlike a generic RLS warning, this inspects ACTUAL inherited table privileges
AND schema USAGE for the PostgreSQL 'anon', 'authenticated' and 'service_role'
roles. RLS off alone does not establish public access. Neither absence of API
grants nor full RLS establishes 4-company application-level isolation.

NO data rows, bank balances, users or secrets are read. No DDL, grants or
provider backup state changes. External restore and ownership verification
remain unverified even if all security catalog checks pass.
"""
from scripts.postgres_connection import sslmode_for
from scripts.staging_transaction_smoke import validate_test_url
from scripts.postgres_live_schema import schema_ddl_steps
from scripts.postgres_company_scope import CRITICAL_TABLES

SCHEMA = "ct_app"
REQUIRED_MIGRATION_TABLES = (
    "legal_entities", "company_read_grants", "company_write_grants",
    "company_warehouse_scope", "company_operation_audit",
)
ACTORS = ("anon", "authenticated", "service_role")
COLUMNS = ("table", "rls", "force_rls", "anon_read", "anon_write",
           "authenticated_read", "authenticated_write",
           "service_role_read", "service_role_write")
assert len(CRITICAL_TABLES) == 8


def _default(status="failed"):
    return {
        "status": status, "total_tables": 0, "rls_enabled": 0,
        "force_rls": 0, "owner_columns": 0, "registry_tables": 0,
        "rls_policy_tables": 0,
        "api_direct_access": {role: 0 for role in ACTORS},
        "api_direct_writes": {role: 0 for role in ACTORS},
        "current_session_elevated": None,
        "company_isolation_verified": False,
        "actual_backup_restore_verified": False,
        "ready_for_production_cutover": False,
    }


def summarize_access_catalog(rows, owner_columns, registries,
                             policy_tables, elevated):
    """Conservative fixed-schema aggregator; never returns business rows."""
    report = _default("review_required")
    if not isinstance(rows, (list, tuple)) or len(rows) != 26:
        return _default()
    try:
        names, _, _ = schema_ddl_steps()
        allowed = set(names)
    except Exception:
        return _default()
    if (len(allowed) != 26
            or not isinstance(registries, (list, tuple))
            or len(registries) != len(REQUIRED_MIGRATION_TABLES)
            or any(type(x) is not bool for x in registries)
            or type(owner_columns) is not int
            or not 0 <= owner_columns <= len(CRITICAL_TABLES)
            or type(policy_tables) is not int
            or not 0 <= policy_tables <= len(rows)
            or not isinstance(elevated, (tuple, list))
            or len(elevated) != 3
            or any(type(v) is not bool for v in elevated)):
        return _default()
    seen = set()
    count_rls = 0
    count_force = 0
    access = {role: 0 for role in ACTORS}
    writes = {role: 0 for role in ACTORS}
    for row in rows:
        if (not isinstance(row, (tuple, list)) or len(row) != len(COLUMNS)
                or row[0] not in allowed or row[0] in seen
                or any(type(v) is not bool for v in row[1:])):
            return _default()
        seen.add(row[0])
        count_rls += int(row[1])
        count_force += int(row[2])
        for index, role in enumerate(ACTORS):
            readable, writable = row[3 + index * 2:5 + index * 2]
            access[role] += int(readable or writable)
            writes[role] += int(writable)
    if seen != allowed:
        return _default()

    report.update({
        "total_tables": len(rows),
        "rls_enabled": count_rls,
        "force_rls": count_force,
        "owner_columns": owner_columns,
        "registry_tables": sum(registries),
        "rls_policy_tables": policy_tables,
        "api_direct_access": access,
        "api_direct_writes": writes,
        "current_session_elevated": any(elevated),
    })
    if any(access.values()):
        report["status"] = "api_permissions_review"
    elif (owner_columns != len(CRITICAL_TABLES)
          or not all(registries) or count_rls != len(rows)):
        report["status"] = "tenant_migration_incomplete"
    # Even with owner columns, RLS and zero grants, signed principal, actual
    # restore, row-level role grants, route audit and ledger QA remain undone.
    return report


def inspect_access_catalog_on_cursor(cur):
    """Read only pg_catalog metadata; never query user/business tables."""
    cur.execute(
        "SELECT c.relname, c.relrowsecurity, c.relforcerowsecurity, "
        "COALESCE(bool_or(r.rolname='anon' AND "
        "has_schema_privilege(r.oid,n.oid,'USAGE') AND "
        "has_table_privilege(r.oid,c.oid,'SELECT')),FALSE), "
        "COALESCE(bool_or(r.rolname='anon' AND "
        "has_schema_privilege(r.oid,n.oid,'USAGE') AND ("
        "has_table_privilege(r.oid,c.oid,'INSERT') OR "
        "has_table_privilege(r.oid,c.oid,'UPDATE') OR "
        "has_table_privilege(r.oid,c.oid,'DELETE'))),FALSE), "
        "COALESCE(bool_or(r.rolname='authenticated' AND "
        "has_schema_privilege(r.oid,n.oid,'USAGE') AND "
        "has_table_privilege(r.oid,c.oid,'SELECT')),FALSE), "
        "COALESCE(bool_or(r.rolname='authenticated' AND "
        "has_schema_privilege(r.oid,n.oid,'USAGE') AND ("
        "has_table_privilege(r.oid,c.oid,'INSERT') OR "
        "has_table_privilege(r.oid,c.oid,'UPDATE') OR "
        "has_table_privilege(r.oid,c.oid,'DELETE'))),FALSE), "
        "COALESCE(bool_or(r.rolname='service_role' AND "
        "has_schema_privilege(r.oid,n.oid,'USAGE') AND "
        "has_table_privilege(r.oid,c.oid,'SELECT')),FALSE), "
        "COALESCE(bool_or(r.rolname='service_role' AND "
        "has_schema_privilege(r.oid,n.oid,'USAGE') AND ("
        "has_table_privilege(r.oid,c.oid,'INSERT') OR "
        "has_table_privilege(r.oid,c.oid,'UPDATE') OR "
        "has_table_privilege(r.oid,c.oid,'DELETE'))),FALSE) "
        "FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace "
        "LEFT JOIN pg_roles r ON r.rolname IN "
        "('anon','authenticated','service_role') "
        "WHERE n.nspname='ct_app' AND c.relkind='r' "
        "GROUP BY c.oid,c.relname,c.relrowsecurity,c.relforcerowsecurity "
        "ORDER BY c.relname"
    )
    rows = cur.fetchall()
    cur.execute(
        "SELECT COUNT(DISTINCT c.oid) FROM pg_class c "
        "JOIN pg_namespace n ON n.oid=c.relnamespace "
        "JOIN pg_attribute a ON a.attrelid=c.oid "
        "WHERE n.nspname='ct_app' AND c.relkind='r' "
        "AND a.attname='legal_entity_id' "
        "AND a.attnum>0 AND NOT a.attisdropped "
        "AND c.relname = ANY(%s)",
        (list(CRITICAL_TABLES),),
    )
    owner_columns = cur.fetchone()[0]
    cur.execute(
        "SELECT " + ", ".join(
            "to_regclass('ct_app." + name + "') IS NOT NULL"
            for name in REQUIRED_MIGRATION_TABLES
        )
    )
    registries = cur.fetchone()
    cur.execute(
        "SELECT COUNT(DISTINCT p.polrelid) FROM pg_policy p "
        "JOIN pg_class c ON c.oid=p.polrelid "
        "JOIN pg_namespace n ON n.oid=c.relnamespace "
        "WHERE n.nspname='ct_app' AND c.relkind='r'"
    )
    policy_tables = cur.fetchone()[0]
    cur.execute(
        "SELECT rolsuper,rolbypassrls,rolcreaterole "
        "FROM pg_roles WHERE rolname=current_user"
    )
    elevated = cur.fetchone()
    return summarize_access_catalog(
        rows, owner_columns, registries, policy_tables, elevated
    )


def inspect_company_access_security(url):
    """Administrator-only caller must authenticate before using this method.

    Invalid DB URL, unavailable metadata or SQL errors always yield a
    sanitized non-approval result. No connection is made on import.
    """
    if not validate_test_url(url):
        return _default("invalid_url")
    try:
        import psycopg
        with psycopg.connect(
            str(url).strip(), sslmode=sslmode_for(url),
            connect_timeout=8, autocommit=True,
        ) as connection:
            with connection.transaction():
                with connection.cursor() as cur:
                    cur.execute(
                        "SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY"
                    )
                    cur.execute("SET LOCAL statement_timeout = '20s'")
                    cur.execute("SET LOCAL lock_timeout = '3s'")
                    return inspect_access_catalog_on_cursor(cur)
    except Exception:
        return _default()
