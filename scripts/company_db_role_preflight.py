"""Read-only readiness gates for REAL (not demo) four-company access.

This has no Streamlit route, user/grant writer, migration, role switch or
production-mode toggle. It cannot certify production access. A deployment
requires independently reviewed mapping of signed app login to an actual
least-privileged PostgreSQL session, per-company entitlements and a verified
provider restore.

In particular, checking a PostgreSQL role does not authenticate a browser
user, and a signed session does NOT make an elevated DATABASE_URL safe.
"""
import re

from scripts.four_company_foundation_ddl import private_company_tables

_ROLE = re.compile(r"^[a-z][a-z0-9_]{2,62}$")
_DENIED_ROLES = frozenset({
    "postgres", "supabase_admin", "supabase_auth_admin", "supabase_storage_admin",
    "service_role", "anon", "authenticated", "authenticator", "dashboard_user",
})


def _blocked(issue, inspected=0, visible=0):
    return {
        "status": "blocked",
        "issue_codes": (issue,),
        "tables_checked": inspected,
        "selectable_company_tables": visible,
        "least_privilege_review": False,
        "user_identity_bound": False,
        "company_entitlements_applied": False,
        "production_authorized": False,
    }


def review_postgres_app_role_on_cursor(cur, expected_db_role):
    """Read pg_catalog only, under a CALLER-OWNED READ ONLY transaction.

    expected_db_role MUST come from a reviewed server account/DB-role
    association; never from the browser's company selector or text field.
    No pg_set_role, SET ROLE, DDL, DML, user data or secrets are inspected.

    This gate deliberately rejects SET ROLE delegation in place of a direct
    least-privileged login: CURRENT_USER must equal SESSION_USER, and the role
    must not inherit any other role. Even a pass remains REVIEW_REQUIRED.
    """
    if (not isinstance(expected_db_role, str)
            or not _ROLE.fullmatch(expected_db_role)
            or expected_db_role in _DENIED_ROLES):
        return _blocked("invalid_role_contract")
    try:
        cur.execute(
            "SELECT current_user::text, session_user::text, "
            "r.rolsuper,r.rolbypassrls,r.rolcreaterole,r.rolcreatedb,"
            "r.rolcanlogin, "
            "has_schema_privilege(current_user,'ct_app','USAGE') "
            "FROM pg_roles r WHERE r.rolname=current_user"
        )
        row = cur.fetchone()
        if (not isinstance(row, (tuple, list)) or len(row) != 8
                or not all(type(x) is bool for x in row[2:])
                or not isinstance(row[0], str)
                or not isinstance(row[1], str)):
            return _blocked("role_metadata_unavailable")
        current, session = row[:2]
        if (current != expected_db_role or session != current
                or not row[6]):
            return _blocked("not_direct_authenticated_db_role")
        if any(row[i] for i in (2, 3, 4, 5)):
            return _blocked("elevated_db_role")
        if not row[7]:
            return _blocked("no_schema_usage")

        # Membership of *any* other PostgreSQL role is an unreviewed
        # escalation path, including roles with inherited or SET privileges.
        cur.execute(
            "SELECT COUNT(*) FROM pg_roles r WHERE "
            "r.rolname <> current_user AND "
            "pg_has_role((SELECT oid FROM pg_roles WHERE rolname=current_user),r.oid,'MEMBER')"
        )
        membership = cur.fetchone()
        if (not isinstance(membership, (tuple, list))
                or len(membership) != 1
                or type(membership[0]) is not int):
            return _blocked("membership_metadata_unavailable")
        if membership[0] != 0:
            return _blocked("unreviewed_role_memberships")

        cur.execute(
            "SELECT c.relname,c.relrowsecurity,c.relforcerowsecurity,"
            "(c.relowner=(SELECT oid FROM pg_roles WHERE rolname=current_user)),"
            "has_table_privilege(current_user,c.oid,'SELECT'),"
            "has_table_privilege(current_user,c.oid,'INSERT'),"
            "(SELECT COUNT(*) FROM pg_policy p WHERE p.polrelid=c.oid "
            "AND p.polcmd IN ('r','*')),"
            "(SELECT COUNT(*) FROM pg_policy p WHERE p.polrelid=c.oid "
            "AND p.polcmd IN ('a','*')) "
            "FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace "
            "WHERE n.nspname='ct_app' AND c.relkind IN ('r','p') "
            "AND c.relname = ANY(%s) ORDER BY c.relname",
            (list(private_company_tables()),),
        )
        rows = cur.fetchall()
        expected = set(private_company_tables())
        if (not isinstance(rows, (tuple, list)) or len(rows) != 23
                or set(item[0] for item in rows
                       if isinstance(item, (tuple, list)) and item)
                != expected):
            return _blocked("owner_table_inventory_incomplete")
        visible = 0
        for record in rows:
            if (not isinstance(record, (tuple, list)) or len(record) != 8
                    or any(type(x) is not bool for x in record[1:6])
                    or any(type(x) is not int or x < 0 for x in record[6:])):
                return _blocked("owner_table_metadata_unavailable")
            if record[3]:
                return _blocked("company_table_owner_role", 23, visible)
            if not record[1] or not record[2] or not record[6] or not record[7]:
                return _blocked("company_rls_missing", 23, visible)
            visible += int(record[4])
        if visible == 0:
            return _blocked("no_business_table_privileges", 23, 0)
        # This is only a catalog prerequisite, not proof that policies
        # correctly filter actual data. The 23-table CI role tests separately
        # verify negative access; a real DB session+login still needs review.
        return {
            "status": "review_required",
            "issue_codes": (),
            "tables_checked": 23,
            "selectable_company_tables": visible,
            "least_privilege_review": True,
            "user_identity_bound": False,
            "company_entitlements_applied": False,
            "production_authorized": False,
        }
    except Exception:
        return _blocked("metadata_unavailable")
