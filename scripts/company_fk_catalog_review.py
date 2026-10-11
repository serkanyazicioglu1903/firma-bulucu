"""Read-only PostgreSQL FK validation for a proposed 26-table company blueprint.

Complements company_isolation_blueprint_review, which validates only the
human-proposed policy *shape*. This module checks whether every inherited
owner path has an ACTUAL, validated, non-null single-column FK to its declared
parent's id in the given ct_app schema. It NEVER establishes that the parent
has been assigned a legal owner, that any user has rights, or that production
is safe. No DDL, DML, business rows, secrets or data are read or written.
"""
from scripts.company_isolation_blueprint_review import review_isolation_blueprint
from scripts.postgres_company_full_coverage import _catalog_tables
from scripts.postgres_connection import sslmode_for
from scripts.staging_transaction_smoke import validate_test_url

SCHEMA = "ct_app"
MAX_FK_ROWS = 500


def _blocked(code):
    return {
        "status": "blocked",
        "issue_codes": (code,),
        "checked_tables": 0,
        "proposed_parent_paths": 0,
        "validated_parent_paths": 0,
        "legal_ownership_verified": False,
        "database_company_isolation_verified": False,
        "real_user_permissions_verified": False,
        "production_approved": False,
    }


def evaluate_blueprint_fks(blueprint, physical_tables, fk_rows):
    """Require actual nonnullable, validated physical FKs for inherited paths.

    Physical rows: (child_table, child_column, parent_table, parent_column,
                    child_not_null, fk_validated), each from pg_catalog.
    This does NOT approve the tenant policy even on a structural match.
    """
    decision = review_isolation_blueprint(blueprint)
    if decision.get("status") != "review_required":
        return _blocked("invalid_blueprint")
    expected = _catalog_tables()
    if (not isinstance(physical_tables, (list, tuple))
            or len(physical_tables) != len(expected)
            or any(not isinstance(t, str) for t in physical_tables)
            or set(physical_tables) != expected):
        return _blocked("schema_mismatch")
    if (not isinstance(fk_rows, (tuple, list)) or len(fk_rows) > MAX_FK_ROWS):
        return _blocked("invalid_fk_catalog")

    catalog = set()
    for row in fk_rows:
        if (not isinstance(row, (tuple, list)) or len(row) != 6
                or any(not isinstance(v, str) for v in row[:4])
                or row[0] not in expected or row[2] not in expected
                or type(row[4]) is not bool or type(row[5]) is not bool):
            return _blocked("invalid_fk_catalog")
        # A physical duplicate may be harmless but merits human review,
        # rather than silently accepting an ambiguous relationship.
        if tuple(row[:4]) in catalog:
            return _blocked("duplicate_fk_catalog")
        catalog.add(tuple(row[:4]))
    # Metadata can include only complete six-column entries. Keep flags in a
    # separate fixed-key map for exact comparisons.
    actual = {tuple(row[:4]): (row[4], row[5]) for row in fk_rows}
    paths = [
        row for row in blueprint["tables"]
        if row["mode"] == "parent_scoped"
    ]
    for proposal in paths:
        key = (
            proposal["table"],
            proposal["fk_column"],
            proposal["parent_table"],
            "id",
        )
        if key not in actual:
            return _blocked("missing_physical_fk")
        child_not_null, validated = actual[key]
        if not validated:
            return _blocked("unvalidated_fk")
        if not child_not_null:
            return _blocked("nullable_parent_fk")
    return {
        "status": "review_required",
        "issue_codes": (),
        "checked_tables": len(expected),
        "proposed_parent_paths": len(paths),
        "validated_parent_paths": len(paths),
        "legal_ownership_verified": False,
        "database_company_isolation_verified": False,
        "real_user_permissions_verified": False,
        "production_approved": False,
    }


def inspect_blueprint_fks_on_cursor(cur, blueprint):
    """Fixed catalog SELECT only, caller owns read-only transaction."""
    if review_isolation_blueprint(blueprint).get("status") != "review_required":
        return _blocked("invalid_blueprint")
    cur.execute(
        "SELECT c.relname FROM pg_class c "
        "JOIN pg_namespace n ON n.oid=c.relnamespace "
        "WHERE n.nspname=%s AND c.relkind IN ('r','p') "
        "ORDER BY c.relname",
        (SCHEMA,),
    )
    table_names = [row[0] for row in cur.fetchall()]
    # Only single-column FK references to the declared parent primary-key
    # column 'id' can be a direct inheritance path. Composite keys must be
    # explicitly designed/reviewed before any approval.
    cur.execute(
        "SELECT child.relname, ca.attname, parent.relname, pa.attname, "
        "ca.attnotnull, f.convalidated "
        "FROM pg_constraint f "
        "JOIN pg_class child ON child.oid=f.conrelid "
        "JOIN pg_namespace nc ON nc.oid=child.relnamespace "
        "JOIN pg_class parent ON parent.oid=f.confrelid "
        "JOIN pg_namespace np ON np.oid=parent.relnamespace "
        "JOIN pg_attribute ca ON ca.attrelid=child.oid "
        "AND ca.attnum=f.conkey[1] AND NOT ca.attisdropped "
        "JOIN pg_attribute pa ON pa.attrelid=parent.oid "
        "AND pa.attnum=f.confkey[1] AND NOT pa.attisdropped "
        "WHERE f.contype='f' AND nc.nspname=%s AND np.nspname=%s "
        "AND array_length(f.conkey,1)=1 "
        "AND array_length(f.confkey,1)=1 "
        "ORDER BY child.relname, ca.attname, parent.relname",
        (SCHEMA, SCHEMA),
    )
    return evaluate_blueprint_fks(blueprint, table_names, cur.fetchall())


def inspect_blueprint_fks(url, blueprint):
    """Opt-in read-only connection. Never prints raw SQL errors/DB content."""
    if review_isolation_blueprint(blueprint).get("status") != "review_required":
        return _blocked("invalid_blueprint")
    if not validate_test_url(url):
        return _blocked("invalid_url")
    try:
        import psycopg
        with psycopg.connect(
            str(url).strip(), sslmode=sslmode_for(url),
            connect_timeout=8, autocommit=True,
        ) as conn:
            with conn.transaction():
                with conn.cursor() as cur:
                    cur.execute(
                        "SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY"
                    )
                    cur.execute("SET LOCAL statement_timeout = '12s'")
                    cur.execute("SET LOCAL lock_timeout = '3s'")
                    return inspect_blueprint_fks_on_cursor(cur, blueprint)
    except Exception:
        return _blocked("metadata_unavailable")
