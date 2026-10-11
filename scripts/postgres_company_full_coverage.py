"""Read-only 26-table ownership coverage preflight for four-company cutover.

All entities/permissions remain UNAPPROVED. This module only reads pg_catalog
metadata, never business records. It does not execute migrations, RLS changes,
GRANT/REVOKE, ownership backfills or user/company assignments.

Eight existing business tables need direct non-null legal owners, but a safe
release ALSO requires a reviewed decision for every other CRM, finance child,
shared master and administrative table. No catalog column proves isolation.
"""
from scripts.postgres_company_scope import CRITICAL_TABLES
from scripts.postgres_connection import sslmode_for
from scripts.postgres_live_schema import schema_ddl_steps
from scripts.staging_transaction_smoke import validate_test_url

SCHEMA = "ct_app"

# These are REVIEW CATEGORIES, not promises that any table may be shared.
# 'parent_review' and 'derived_review' are NOT granted an owner by inference.
REVIEW_GROUPS = {
    "direct_owner_required": tuple(CRITICAL_TABLES),
    "shared_master_decision": ("product_catalog",),
    "parent_ownership_decision": ("customers", "warehouses", "tasks"),
    "derived_ownership_decision": (
        "opportunities", "contacts", "activities",
        "opportunity_stage_history", "customer_product_status", "quotes",
        "inventory_policy", "cash_events", "quality_actions",
        "quality_recoveries", "compliance_documents", "regulatory_items",
    ),
    "internal_access_decision": ("audit_log", "system_settings"),
}


def _catalog_tables():
    names, _, _ = schema_ddl_steps()
    expected = set(names)
    groups = [name for group in REVIEW_GROUPS.values() for name in group]
    if (len(expected) != 26 or len(groups) != 26
            or len(set(groups)) != 26 or set(groups) != expected
            or set(REVIEW_GROUPS["direct_owner_required"]) != set(CRITICAL_TABLES)):
        raise ValueError("unreviewed_table_inventory")
    return expected


def _failed(status="failed"):
    return {
        "status": status,
        "table_count": 0,
        "rls_enabled_count": 0,
        "direct_owner_count": 0,
        "required_nonnull_owner_count": 0,
        "missing_required_owner": (),
        "nullable_required_owner": (),
        "tables_needing_design_review": (),
        "four_company_isolation_verified": False,
        "live_migration_approved": False,
    }


def classify_catalog_rows(rows):
    """Validate exactly 26 metadata rows and identify missing preconditions.

    Input row: (table_name, has_legal_entity_id, legal_entity_id_not_null,
                rls_enabled). All flags must be real booleans.
    No pathway returns 'approved': actual row ownership, SQL routes, distinct
    user roles, RLS policies and full backup restore have separate signoffs.
    """
    try:
        expected = _catalog_tables()
    except Exception:
        return _failed("invalid_inventory")
    if not isinstance(rows, (list, tuple)) or len(rows) != len(expected):
        return _failed("schema_mismatch")
    observed = {}
    for row in rows:
        if (not isinstance(row, (list, tuple)) or len(row) != 4
                or not isinstance(row[0], str) or row[0] not in expected
                or row[0] in observed
                or any(type(v) is not bool for v in row[1:])
                or (row[2] and not row[1])):
            return _failed("invalid_metadata")
        observed[row[0]] = tuple(row[1:])
    if set(observed) != expected:
        return _failed("schema_mismatch")

    critical = set(CRITICAL_TABLES)
    missing = tuple(sorted(t for t in critical if not observed[t][0]))
    nullable = tuple(sorted(t for t in critical if observed[t][0]
                            and not observed[t][1]))
    pending = tuple(sorted(t for t in expected - critical))
    return {
        "status": "ownership_structure_incomplete" if missing or nullable
                  else "review_required",
        "table_count": len(observed),
        "rls_enabled_count": sum(int(v[2]) for v in observed.values()),
        "direct_owner_count": sum(int(v[0]) for v in observed.values()),
        "required_nonnull_owner_count": sum(
            int(observed[t][0] and observed[t][1]) for t in critical
        ),
        "missing_required_owner": missing,
        "nullable_required_owner": nullable,
        # Even if these tables later receive columns or RLS, their legal
        # ownership/visibility and joined/export read paths need signoff.
        "tables_needing_design_review": pending,
        "four_company_isolation_verified": False,
        "live_migration_approved": False,
    }


def inspect_catalog_on_cursor(cur):
    """Only pg_catalog metadata, fixed schema and fixed names."""
    expected = _catalog_tables()
    cur.execute(
        "SELECT c.relname, a.attnum IS NOT NULL AS has_owner, "
        "COALESCE(a.attnotnull, FALSE) AS owner_not_null, c.relrowsecurity "
        "FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace "
        "LEFT JOIN pg_attribute a ON a.attrelid = c.oid "
        "AND a.attname = 'legal_entity_id' AND a.attnum > 0 "
        "AND NOT a.attisdropped "
        "WHERE n.nspname = %s AND c.relkind IN ('r','p') "
        "AND c.relname = ANY(%s) ORDER BY c.relname",
        (SCHEMA, sorted(expected)),
    )
    return classify_catalog_rows(cur.fetchall())


def inspect_live_company_ownership(url):
    """Run on explicit request; fail closed; never return customer data."""
    if not validate_test_url(url):
        return _failed("invalid_url")
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
                    return inspect_catalog_on_cursor(cur)
    except Exception:
        # DB errors can contain connection details: do not echo exceptions.
        return _failed()
