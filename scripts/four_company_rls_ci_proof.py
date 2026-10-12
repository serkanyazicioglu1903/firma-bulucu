"""CI-ONLY PostgreSQL role-level RLS rehearsal covering 23 company business tables.

This module does NOT connect to any database, has no production runner and
must never be used as production RLS/app authorization SQL. Its SQL is run
ONLY inside an automatically rolled-back disposable PostgreSQL test.

The current app's elevated database connection can bypass RLS. A real
production rollout needs a trusted least-privileged per-user DB identity,
an independently reviewed grant administration design, cross-table FK checks,
safe shared product catalogue/internal table access and full disaster recovery.
"""
from scripts.four_company_foundation_ddl import private_company_tables

CI_ROLES = (
    "ct_ci_23_rls_a", "ct_ci_23_rls_b",
    "ct_ci_23_rls_c", "ct_ci_23_rls_d",
)


def ci_23_table_rls_sql():
    """Return reviewed synthetic role/policy statements, without executing.

    Restricts SELECT/INSERT by PostgreSQL's CURRENT_USER, never user-supplied
    Streamlit role labels or session-selected company codes.
    This rehearsal intentionally uses SELECT-accessible synthetic grant
    tables and broad test-only table privileges, NOT production grants.
    """
    tables = private_company_tables()
    if len(tables) != 23:
        raise ValueError("unexpected_company_table_count")
    role_names = ", ".join(CI_ROLES)
    statements = [
        *(f"CREATE ROLE {role} NOLOGIN NOINHERIT NOSUPERUSER NOBYPASSRLS"
          for role in CI_ROLES),
        f"GRANT USAGE ON SCHEMA ct_app TO {role_names}",
        f'GRANT SELECT ON "ct_app"."company_read_grants", '
        f'"ct_app"."company_write_grants" TO {role_names}',
    ]
    for table in tables:
        target = f'"ct_app"."{table}"'
        row = f'"{table}".legal_entity_id'
        statements.extend((
            f"ALTER TABLE {target} ENABLE ROW LEVEL SECURITY",
            f"ALTER TABLE {target} FORCE ROW LEVEL SECURITY",
            f"GRANT SELECT, INSERT ON {target} TO {role_names}",
            f"CREATE POLICY ci_23_company_read ON {target} "
            f"FOR SELECT TO {role_names} USING (EXISTS ("
            'SELECT 1 FROM "ct_app"."company_read_grants" g '
            f"WHERE g.principal_id=CURRENT_USER "
            f"AND g.legal_entity_id={row} AND g.can_read=TRUE))",
            f"CREATE POLICY ci_23_company_insert ON {target} "
            f"FOR INSERT TO {role_names} WITH CHECK (EXISTS ("
            'SELECT 1 FROM "ct_app"."company_write_grants" g '
            f"WHERE g.principal_id=CURRENT_USER "
            f"AND g.legal_entity_id={row} AND g.can_write=TRUE))",
        ))
    return tuple(statements)
