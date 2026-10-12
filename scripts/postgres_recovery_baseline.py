"""Read-only, repeatable-read backup/restore baseline for ct_app (26 tables).

Captures table counts, schema/ownership/RLS/policy metadata fingerprint.
NEVER reads business columns or exports business records. A matching baseline
alone cannot prove backup origin, row integrity, grants, PITR or actual
provider-managed restoration, and can NEVER authorize a live cutover.
The same inspector can run against a separately approved isolated restore
for a *preliminary* count/catalog comparison.

No automatic backup, copying or restore operations occur in this module.
"""
import hashlib
import json

from scripts.postgres_connection import sslmode_for
from scripts.postgres_live_schema import schema_ddl_steps
from scripts.staging_transaction_smoke import validate_test_url

SCHEMA = "ct_app"
MAX_ROW_COUNT = 10**14


def _denied(code):
    return {
        "status": code,
        "tables": 0,
        "rows": None,
        "schema_sha256": None,
        "counts_sha256": None,
        "counts": {},
        "provider_backup_verified": False,
        "provider_restore_verified": False,
        "four_company_isolation_verified": False,
        "production_cutover_approved": False,
    }


def _expected():
    names, _, _ = schema_ddl_steps()
    if len(names) != 26 or len(set(names)) != 26:
        raise ValueError("unreviewed_table_inventory")
    return tuple(sorted(names))


def capture_legacy_baseline_on_cursor(cur, *, schema=SCHEMA):
    """PostgreSQL catalog and 26 COUNT(*) calls ONLY, in caller-owned txn.

    Refuses partial company migrations because legacy 26-table ZIP would
    omit any new legal-entity registries, grants, RLS/policy definitions.
    Does not return raw row contents or schema SQL.
    """
    if schema not in ("ct_app", "ct_restore_verify"):
        return _denied("invalid_schema")
    try:
        expected = _expected()
        cur.execute(
            "SELECT c.relname, c.relrowsecurity, c.relforcerowsecurity, "
            "EXISTS(SELECT 1 FROM pg_attribute a WHERE a.attrelid=c.oid "
            "AND a.attnum>0 AND NOT a.attisdropped "
            "AND a.attname='legal_entity_id'), "
            "EXISTS(SELECT 1 FROM pg_policy p WHERE p.polrelid=c.oid) "
            "FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace "
            "WHERE n.nspname=%s AND c.relkind IN ('r','p') ORDER BY c.relname",
            (schema,),
        )
        metadata = cur.fetchall()
        if (len(metadata) != 26 or tuple(row[0] for row in metadata) != expected
                or any(
                    not isinstance(row, (tuple, list)) or len(row) != 5
                    or any(type(flag) is not bool for flag in row[1:])
                    for row in metadata
                )):
            return _denied("schema_mismatch")
        if any(any(row[1:]) for row in metadata):
            return _denied("company_migration_started")

        # PostgreSQL FK/column semantics are fingerprinted without
        # serializing column values or SQL view definitions to the caller.
        cur.execute(
            "SELECT c.relname, a.attname, a.atttypid::regtype::text, "
            "a.attnotnull FROM pg_class c "
            "JOIN pg_namespace n ON n.oid=c.relnamespace "
            "JOIN pg_attribute a ON a.attrelid=c.oid "
            "WHERE n.nspname=%s AND c.relkind IN ('r','p') "
            "AND a.attnum>0 AND NOT a.attisdropped "
            "ORDER BY c.relname,a.attnum",
            (schema,),
        )
        columns = cur.fetchall()
        if (not columns or
                any(
                    not isinstance(row, (tuple, list)) or len(row) != 4
                    or row[0] not in expected
                    or not isinstance(row[1], str)
                    or not isinstance(row[2], str)
                    or type(row[3]) is not bool
                    for row in columns
                ) or set(row[0] for row in columns) != set(expected)):
            return _denied("invalid_schema_metadata")
        schema_sha = hashlib.sha256(
            json.dumps(columns, separators=(",", ":"),
                       ensure_ascii=True).encode()
        ).hexdigest()

        # For the special system_settings PK, COUNT is still safe and does
        # not fetch setting keys/values.
        from psycopg import sql
        counts = {}
        for name in expected:
            cur.execute(sql.SQL("SELECT COUNT(*) FROM {}").format(
                sql.Identifier(schema, name)
            ))
            raw = cur.fetchone()
            if (not isinstance(raw, (tuple, list)) or len(raw) != 1
                    or type(raw[0]) is not int or
                    not 0 <= raw[0] <= MAX_ROW_COUNT):
                return _denied("invalid_row_count")
            counts[name] = raw[0]
        digest = hashlib.sha256(
            json.dumps(counts, sort_keys=True,
                       separators=(",", ":")).encode()
        ).hexdigest()
        return {
            "status": "baseline_captured",
            "tables": 26,
            "rows": sum(counts.values()),
            "schema_sha256": schema_sha,
            "counts_sha256": digest,
            "counts": counts,
            "provider_backup_verified": False,
            "provider_restore_verified": False,
            "four_company_isolation_verified": False,
            "production_cutover_approved": False,
        }
    except Exception:
        return _denied("metadata_unavailable")


def read_legacy_baseline(url):
    """Open ONLY a repeatable-read, read-only transaction on supplied DB URL."""
    if not validate_test_url(url):
        return _denied("invalid_url")
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
                    cur.execute("SET LOCAL statement_timeout = '20s'")
                    cur.execute("SET LOCAL lock_timeout = '3s'")
                    return capture_legacy_baseline_on_cursor(cur)
    except Exception:
        return _denied("metadata_unavailable")


def compare_isolated_restore_baselines(source, restored):
    """Compare separately collected aggregate-only fingerprints.

    Matching source/restore counts and columns is a *preliminary* check:
    never treat caller-provided evidence as proof that provider-managed
    backup was restored, nor as a business-value/permission reconciliation.
    """
    if not isinstance(source, dict) or not isinstance(restored, dict):
        return {
            "status": "invalid_evidence", "schema_match": False,
            "counts_match": False, "source_records": None,
            "provider_restore_verified": False,
            "production_cutover_approved": False,
        }
    ok = all(
        row.get("status") == "baseline_captured"
        and row.get("tables") == 26
        and type(row.get("rows")) is int
        and isinstance(row.get("counts"), dict)
        and set(row["counts"]) == set(_expected())
        and all(type(value) is int and value >= 0
                for value in row["counts"].values())
        and isinstance(row.get("schema_sha256"), str)
        and isinstance(row.get("counts_sha256"), str)
        and len(row["schema_sha256"]) == 64
        and len(row["counts_sha256"]) == 64
        and row["rows"] == sum(row["counts"].values())
        and hashlib.sha256(json.dumps(
            row["counts"], sort_keys=True,
            separators=(",", ":")).encode()).hexdigest() == row["counts_sha256"]
        for row in (source, restored)
    )
    if not ok:
        return {
            "status": "invalid_evidence", "schema_match": False,
            "counts_match": False, "source_records": None,
            "provider_restore_verified": False,
            "production_cutover_approved": False,
        }
    schema_match = source["schema_sha256"] == restored["schema_sha256"]
    counts_match = source["counts_sha256"] == restored["counts_sha256"]
    return {
        "status": "review_required" if schema_match and counts_match
                  else "restore_mismatch",
        "schema_match": schema_match,
        "counts_match": counts_match,
        "source_records": source["rows"],
        "provider_restore_verified": False,
        "production_cutover_approved": False,
    }
