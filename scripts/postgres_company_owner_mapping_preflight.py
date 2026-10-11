"""READ-ONLY four-company owner mapping preflight — never applies mappings.

A source snapshot consists ONLY of fixed-table row IDs, internal FK IDs and
row fingerprints computed by PostgreSQL. No customer names, prices, bank
numbers, addresses or commercial content are returned from the database.

The proposed ownership manifest is supplied by an independent human/legal
review: NO code derives ownership from company names, existing fields, IDs or
related records. The manifest must cover EVERY row of all eight tables,
carry an evidence reference per row, and match an unchanged source fingerprint.

Passing returns "review_required", NEVER approved or production-ready.
There are no INSERT/UPDATE/ALTER statements or automated mapping commands.
"""
from hashlib import sha256
import json
import re

from scripts.group_company_catalog import COMPANY_LABELS
from scripts.postgres_company_scope import CRITICAL_TABLES
from scripts.postgres_connection import sslmode_for
from scripts.postgres_legal_entity_rehearsal import OWNED_RELATIONSHIPS
from scripts.staging_transaction_smoke import validate_test_url

MAX_TABLE_ROWS = 20000
MAX_TOTAL_ROWS = 100000
EVIDENCE_REF = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/-]{5,127}$")
HEX32 = re.compile(r"^[0-9a-f]{32}$")
HEX64 = re.compile(r"^[0-9a-f]{64}$")

# Every structural link below has a fixed, reviewed SQL column identifier.
PARENT_FKS = {
    table: tuple((field, parent) for child, field, parent
                 in OWNED_RELATIONSHIPS if child == table)
    for table in CRITICAL_TABLES
}
assert len(CRITICAL_TABLES) == 8
assert {child for child, _, _ in OWNED_RELATIONSHIPS} <= set(CRITICAL_TABLES)


def _safe_pk(value):
    return type(value) is int and value > 0


def snapshot_digest(snapshot):
    """Deterministic full-row drift fingerprint, not an authentication token."""
    if not isinstance(snapshot, dict) or set(snapshot) != set(CRITICAL_TABLES):
        raise ValueError("invalid_snapshot")
    total = 0
    normalized = {}
    for table in CRITICAL_TABLES:
        rows = snapshot[table]
        if not isinstance(rows, (tuple, list)) or len(rows) > MAX_TABLE_ROWS:
            raise ValueError("invalid_snapshot")
        seen = set()
        ordered = []
        for entry in rows:
            expected = {"id", "row_hash"} | {f for f, _ in PARENT_FKS[table]}
            if not isinstance(entry, dict) or set(entry) != expected:
                raise ValueError("invalid_snapshot")
            ident = entry["id"]
            if not _safe_pk(ident) or ident in seen:
                raise ValueError("invalid_snapshot")
            seen.add(ident)
            if not isinstance(entry["row_hash"], str) or not HEX32.fullmatch(entry["row_hash"]):
                raise ValueError("invalid_snapshot")
            for field, _ in PARENT_FKS[table]:
                ref = entry[field]
                if ref is not None and not _safe_pk(ref):
                    raise ValueError("invalid_snapshot")
            ordered.append(entry)
        total += len(ordered)
        if total > MAX_TOTAL_ROWS:
            raise ValueError("snapshot_too_large")
        normalized[table] = sorted(ordered, key=lambda row: row["id"])
    canonical = json.dumps(
        normalized, sort_keys=True, separators=(",", ":"), ensure_ascii=True
    ).encode("utf-8")
    return sha256(canonical).hexdigest()


def read_owner_graph_on_cursor(cur):
    """Fixed read-only SQL: no owner inference; bounded sensitive row hashes.

    Call only inside a read-only consistent transaction. No data printed.
    """
    result = {}
    for table in CRITICAL_TABLES:
        fks = PARENT_FKS[table]
        fixed_columns = "".join(', t."' + field + '"' for field, _ in fks)
        cur.execute(
            'SELECT t.id, md5(row_to_json(t)::text)' + fixed_columns +
            ' FROM "ct_app"."' + table + '" t ORDER BY t.id LIMIT %s',
            (MAX_TABLE_ROWS + 1,),
        )
        rows = cur.fetchall()
        if len(rows) > MAX_TABLE_ROWS:
            raise ValueError("snapshot_too_large")
        entries = []
        for row in rows:
            entry = {"id": row[0], "row_hash": row[1]}
            for i, (fk, _) in enumerate(fks):
                entry[fk] = row[i + 2]
            entries.append(entry)
        result[table] = tuple(entries)
    snapshot_digest(result)
    return result


def read_owner_graph(url):
    """Opt-in, read-only snapshot. Returns (status, internal_graph).

    Do not send the graph to a browser; records are metadata intended for
    an authorized local approval workflow, not a public dashboard.
    """
    if not validate_test_url(url):
        return "invalid_url", None
    try:
        import psycopg
        with psycopg.connect(
            str(url).strip(), connect_timeout=8, sslmode=sslmode_for(url),
            autocommit=True,
        ) as conn:
            with conn.transaction():
                with conn.cursor() as cur:
                    cur.execute(
                        "SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY"
                    )
                    cur.execute("SET LOCAL statement_timeout = '20s'")
                    cur.execute("SET LOCAL lock_timeout = '3s'")
                    result = read_owner_graph_on_cursor(cur)
        return "ok", result
    except ValueError:
        return "blocked", None
    except Exception:
        return "failed", None


def evaluate_owner_mapping(snapshot, manifest):
    """Strict offline validation. Returns counts and issue codes, never rows.

    manifest: {source_sha256: ..., allocations: {table: [
      {record_id: int, company_code: explicit known code,
       evidence_ref: human-reviewed opaque reference}]}}

    A good manifest STILL requires legal, operations and finance sign-off.
    """
    base = {
        "status": "blocked", "isolation_verified": False,
        "auto_assigned": False, "manual_approval_required": True,
        "source_fingerprint_matches": False,
        "checked_tables": len(CRITICAL_TABLES),
        "checked_rows": 0, "issue_codes": (),
    }
    try:
        digest = snapshot_digest(snapshot)
    except (ValueError, TypeError):
        return {**base, "issue_codes": ("invalid_snapshot",)}
    total = sum(len(snapshot[t]) for t in CRITICAL_TABLES)
    base["checked_rows"] = total
    if (not isinstance(manifest, dict)
            or set(manifest) != {"source_sha256", "allocations"}
            or not isinstance(manifest.get("source_sha256"), str)
            or not HEX64.fullmatch(manifest["source_sha256"])
            or manifest["source_sha256"] != digest):
        return {**base, "issue_codes": ("stale_or_invalid_source",)}
    base["source_fingerprint_matches"] = True
    allocations = manifest["allocations"]
    if not isinstance(allocations, dict) or set(allocations) != set(CRITICAL_TABLES):
        return {**base, "issue_codes": ("incomplete_tables",)}

    # No automatic propagation from parent records or from one legal entity
    # to another; each row requires explicit evidence.
    owner_maps = {}
    problems = set()
    for table in CRITICAL_TABLES:
        entries = allocations[table]
        if not isinstance(entries, list) or len(entries) > MAX_TABLE_ROWS:
            problems.add("invalid_allocations")
            continue
        expected_ids = {row["id"] for row in snapshot[table]}
        assigned = {}
        for item in entries:
            if not isinstance(item, dict) or set(item) != {
                "record_id", "company_code", "evidence_ref"
            }:
                problems.add("invalid_allocations")
                continue
            record_id = item["record_id"]
            company = item["company_code"]
            evidence = item["evidence_ref"]
            if (not _safe_pk(record_id) or record_id in assigned
                    or not isinstance(company, str)
                    or company not in COMPANY_LABELS
                    or not isinstance(evidence, str)
                    or not EVIDENCE_REF.fullmatch(evidence)):
                problems.add("invalid_allocations")
                continue
            assigned[record_id] = company
        if set(assigned) != expected_ids:
            problems.add("missing_or_extra_rows")
        owner_maps[table] = assigned

    if problems:
        return {**base, "issue_codes": tuple(sorted(problems))}
    for table in CRITICAL_TABLES:
        for row in snapshot[table]:
            company = owner_maps[table][row["id"]]
            for field, parent in PARENT_FKS[table]:
                parent_id = row[field]
                if parent_id is None:
                    continue
                parent_company = owner_maps[parent].get(parent_id)
                if parent_company is None:
                    problems.add("missing_parent_record")
                elif parent_company != company:
                    problems.add("cross_company_relation")
    if total == 0:
        problems.add("empty_source_not_tested")
    if problems:
        return {**base, "issue_codes": tuple(sorted(problems))}
    return {**base, "status": "review_required", "issue_codes": ()}
