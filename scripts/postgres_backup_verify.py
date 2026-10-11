"""Offline in-memory integrity inspection of an AS Control Tower ZIP export.

This does not open a database, extract files to disk, upload to ChatGPT,
restore a database, or inspect/show customers, names, prices or transactions.
It verifies ZIP member allowlist, 26-table checksums, data-row counts and
SQLite-derived column shapes against the checked-in PostgreSQL schema.

Format validation is NOT a disaster-recovery or provider backup certification.
"""
from hashlib import sha256

from scripts.build_pg_schema import sqlite_schema
from scripts.postgres_live_schema import schema_ddl_steps
from scripts.postgres_restore_drill import _parse_and_verify_zip

MAX_FILE_BYTES = 30 * 1024 * 1024


def inspect_export_zip(payload):
    """Returns (status, safe aggregate-only summary).

    status: invalid_file | corrupt_or_wrong_format | verified_format | failed
    No company data, database URL, credentials or archive bytes are returned.
    """
    if not isinstance(payload, bytes) or not 0 < len(payload) <= MAX_FILE_BYTES:
        return "invalid_file", None

    try:
        names, _, _ = schema_ddl_steps()
        if len(names) != 26 or len(set(names)) != 26:
            return "failed", None

        parsed = _parse_and_verify_zip(payload, names)
        if parsed is None:
            return "corrupt_or_wrong_format", None
        batches, manifest = parsed

        with sqlite_schema() as definitions:
            columns = {
                table: frozenset(
                    item[1] for item in definitions.execute(
                        'PRAGMA table_info("' + table + '")'
                    )
                )
                for table in names
            }

        if any(
            set(row) != columns[table]
            for table, rows in batches.items()
            for row in rows
        ):
            return "corrupt_or_wrong_format", None

        # Do not render sensitive archive content. Only counts and SHA.
        safe_counts = {
            name: len(batches[name])
            for name in sorted(names)
        }
        total = sum(safe_counts.values())
        return "verified_format", {
            "table_count": len(names),
            "row_count": total,
            "table_counts": safe_counts,
            "sha256": sha256(payload).hexdigest(),
            "exported_utc": str(manifest.get("captured_utc") or "")[:40],
            "restoration_tested": False,
        }
    except Exception:
        # Never return plaintext, ZIP members or a driver/JSON exception.
        return "failed", None
