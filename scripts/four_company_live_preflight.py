"""Read-only production migration inventory. No DDL, DML, grants or connections.

A snapshot of PostgreSQL catalog metadata is not a backup, not a data owner
manifest, and never proof of production readiness.
"""
from scripts.four_company_foundation_ddl import private_company_tables
from scripts.postgres_company_full_coverage import _catalog_tables

SQL = """
SELECT c.relname::text AS table_name,
       c.reltuples::bigint AS estimated_rows,
       c.relrowsecurity AS rls_enabled,
       c.relforcerowsecurity AS rls_forced,
       EXISTS (
           SELECT 1 FROM pg_attribute a
           WHERE a.attrelid = c.oid AND a.attnum > 0
             AND NOT a.attisdropped AND a.attname = 'legal_entity_id'
       ) AS has_legal_entity_id,
       (SELECT count(*) FROM pg_policy p WHERE p.polrelid = c.oid) AS policy_count
FROM pg_class c
JOIN pg_namespace n ON n.oid = c.relnamespace
WHERE n.nspname = 'ct_app' AND c.relkind IN ('r', 'p')
ORDER BY c.relname
"""


def assess_catalog_rows(rows):
    expected = _catalog_tables()
    if not isinstance(rows, (list, tuple)) or len(rows) != len(expected):
        return {"status": "blocked", "reason": "inventory_mismatch"}
    seen = set()
    for row in rows:
        if not isinstance(row, (list, tuple)) or len(row) != 6:
            return {"status": "blocked", "reason": "invalid_metadata"}
        name, estimated, enabled, forced, has_entity, policy_count = row
        if (name not in expected or name in seen
                or type(estimated) is not int
                or any(type(x) is not bool for x in (enabled, forced, has_entity))
                or type(policy_count) is not int or policy_count < 0):
            return {"status": "blocked", "reason": "invalid_metadata"}
        seen.add(name)
    private = set(private_company_tables())
    missing = tuple(sorted(r[0] for r in rows if r[0] in private and not r[4]))
    unprotected = tuple(sorted(r[0] for r in rows if r[0] in private
                               and not (r[2] and r[3] and r[5] > 0)))
    return {
        "status": "blocked" if missing or unprotected else "review_required",
        "tables": len(rows),
        "private_tables": len(private),
        "missing_owner_column": missing,
        "missing_forced_rls_or_policy": unprotected,
        "estimated_rows_not_a_reconciliation": True,
        "migration_authorized": False,
    }


def inspect_on_cursor(cur):
    """Caller must supply a read-only transaction; reads metadata only."""
    cur.execute(SQL)
    return assess_catalog_rows(cur.fetchall())


def count_existing_rows_on_cursor(cur):
    """Exact read-only row counts; never read customer names or row contents.

    This is a baseline for backup/restore reconciliation, NOT a backup.
    Fixed table names come from the audited 26-table application inventory.
    """
    names = sorted(_catalog_tables())
    counts = {}
    for name in names:
        cur.execute('SELECT count(*) FROM "ct_app"."' + name + '"')
        row = cur.fetchone()
        if (not isinstance(row, (tuple, list)) or len(row) != 1
                or type(row[0]) is not int or row[0] < 0):
            raise ValueError("row_count_unavailable")
        counts[name] = row[0]
    return {
        "status": "review_required",
        "counts": counts,
        "total_rows": sum(counts.values()),
        "row_contents_exposed": False,
        "backup_verified": False,
        "owner_assignments_verified": False,
    }
