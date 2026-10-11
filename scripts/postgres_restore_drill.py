"""Verify ct_app ZIP restoration ONLY in a disposable local PostgreSQL CI DB.

This is deliberately NOT a general-purpose database restore interface:
- It rejects all production/Supabase URLs, regardless of operator approval.
- It requires exact localhost Docker CI database/user/port and explicit CI env.
- It refuses any pre-existing verification schema.
- The restored schema, data and constraints exist only within one PostgreSQL
  transaction which is ALWAYS rolled back before reporting success.
- No secrets, company rows or archive contents appear in results or logs.

A passed drill proves this export format restores in the CI PostgreSQL schema,
not that the owner's provider-managed Supabase PITR/backup service is ready.
"""
import hashlib
from io import BytesIO
import json
import os
from urllib.parse import urlsplit
import zipfile

from scripts.postgres_connection import (
    CI_DATABASE, CI_USER, sslmode_for,
)
from scripts.postgres_live_schema import schema_ddl_steps
from scripts.postgres_backup import MAX_UNCOMPRESSED, MAX_ROWS_PER_TABLE

_RESTORE_SCHEMA = "ct_restore_verify"
_ARCHIVE_MAX = 30 * 1024 * 1024


class _VerifiedRollback(Exception):
    """Control flow to force rollback of all restoration DDL and row inserts."""


def _ci_database_url_only(url):
    if os.environ.get("CT_LOCAL_POSTGRES_TEST") != "1":
        return False
    try:
        parsed = urlsplit(str(url or ""))
        return (
            parsed.scheme in ("postgresql", "postgres")
            and parsed.hostname in ("127.0.0.1", "localhost")
            and parsed.port == 5432
            and parsed.username == CI_USER
            and parsed.path == "/" + CI_DATABASE
            and not parsed.query
            and not parsed.fragment
            and sslmode_for(url) == "disable"
        )
    except (TypeError, ValueError):
        return False


def _parse_and_verify_zip(payload, expected_names):
    if not isinstance(payload, bytes) or len(payload) > _ARCHIVE_MAX:
        return None
    expected_paths = {"manifest.json"} | {
        "tables/" + name + ".json" for name in expected_names
    }
    try:
        with zipfile.ZipFile(BytesIO(payload)) as archive:
            infos = archive.infolist()
            if (len(infos) != len(expected_paths)
                    or set(info.filename for info in infos) != expected_paths):
                return None
            if any(info.is_dir() or info.file_size > MAX_UNCOMPRESSED
                   for info in infos):
                return None
            if sum(info.file_size for info in infos) > MAX_UNCOMPRESSED:
                return None
            manifest = json.loads(archive.read("manifest.json"))
            if (not isinstance(manifest, dict)
                    or manifest.get("format") != "as-control-tower-ct-app-export-v1"
                    or manifest.get("schema") != "ct_app"
                    or not isinstance(manifest.get("tables"), dict)
                    or set(manifest["tables"]) != set(expected_names)):
                return None
            batches = {}
            for name in expected_names:
                content = archive.read("tables/" + name + ".json")
                metadata = manifest["tables"][name]
                if (not isinstance(metadata, dict)
                        or hashlib.sha256(content).hexdigest() != metadata.get("sha256")):
                    return None
                rows = json.loads(content)
                if (not isinstance(rows, list)
                        or len(rows) != metadata.get("row_count")
                        or len(rows) > MAX_ROWS_PER_TABLE
                        or not all(isinstance(row, dict) for row in rows)):
                    return None
                batches[name] = rows
            return batches, manifest
    except (OSError, ValueError, TypeError, KeyError, zipfile.BadZipFile):
        return None


def verify_disposable_backup_restore(url, payload):
    """Return (status, aggregate-only summary) without permanent DB writes.

    Status: forbidden | invalid_archive | existing_schema | verified | failed
    """
    if not _ci_database_url_only(url):
        return "forbidden", None

    try:
        names, create_sql, foreign_keys = schema_ddl_steps()
        if len(names) != 26 or len(set(names)) != 26:
            return "failed", None
        parsed = _parse_and_verify_zip(payload, names)
        if parsed is None:
            return "invalid_archive", None
        batches, _ = parsed

        from scripts.build_pg_schema import sqlite_schema
        with sqlite_schema() as sqlite:
            columns = {
                table: [r[1] for r in sqlite.execute(
                    'PRAGMA table_info("' + table + '")'
                )] for table in names
            }
        for name, rows in batches.items():
            if any(set(row) != set(columns[name]) for row in rows):
                return "invalid_archive", None

        import psycopg
        from psycopg import sql
        from psycopg.rows import dict_row, tuple_row
        from scripts.postgres_recovery_baseline import (
            capture_legacy_baseline_on_cursor,
            compare_isolated_restore_baselines,
        )

        restored_rows = 0
        with psycopg.connect(
            str(url).strip(), sslmode=sslmode_for(url),
            connect_timeout=8, autocommit=True, row_factory=dict_row,
        ) as connection:
            try:
                with connection.transaction():
                    with connection.cursor() as cur:
                        cur.execute("SET LOCAL statement_timeout = '80s'")
                        cur.execute("SET LOCAL lock_timeout = '3s'")
                        cur.execute(
                            "SELECT EXISTS(SELECT 1 FROM pg_namespace WHERE nspname=%s)",
                            (_RESTORE_SCHEMA,),
                        )
                        if cur.fetchone()["exists"]:
                            return "existing_schema", None
                        # Establish an independent read-only source baseline
                        # before the disposable restore; never infer source
                        # ownership or expose raw business rows in the result.
                        with connection.cursor(row_factory=tuple_row) as base_cur:
                            source_baseline = capture_legacy_baseline_on_cursor(
                                base_cur, schema="ct_app"
                            )
                        if source_baseline["status"] != "baseline_captured":
                            raise ValueError("Source recovery baseline incomplete")
                        cur.execute('CREATE SCHEMA "' + _RESTORE_SCHEMA + '"')
                        cur.execute(
                            'SET LOCAL search_path TO "' + _RESTORE_SCHEMA
                            + '", pg_catalog'
                        )
                        for statement in create_sql:
                            cur.execute(statement)

                        for name in names:
                            entries = batches[name]
                            if not entries:
                                continue
                            col_names = columns[name]
                            insert_query = sql.SQL(
                                "INSERT INTO {} ({}) VALUES ({})"
                            ).format(
                                sql.Identifier(name),
                                sql.SQL(",").join(map(sql.Identifier, col_names)),
                                sql.SQL(",").join(
                                    sql.Placeholder() for _ in col_names
                                ),
                            )
                            cur.executemany(
                                insert_query,
                                [tuple(row[c] for c in col_names) for row in entries],
                            )
                            restored_rows += len(entries)

                            # GENERATED BY DEFAULT AS IDENTITY accepts explicit
                            # restored IDs, but the identity sequence would
                            # otherwise restart at 1 and collide on next write.
                            # Repair the sequence in the same ephemeral schema.
                            if "id" in col_names:
                                cur.execute(
                                    "SELECT pg_get_serial_sequence(%s,%s) AS seq",
                                    (_RESTORE_SCHEMA + "." + name, "id"),
                                )
                                sequence = cur.fetchone()["seq"]
                                if sequence is not None:
                                    maximum = max(int(row["id"]) for row in entries)
                                    cur.execute(
                                        "SELECT setval(%s::regclass,%s,true)",
                                        (sequence, maximum),
                                    )
                                    cur.execute(
                                        "SELECT nextval(%s::regclass) AS next_id",
                                        (sequence,),
                                    )
                                    if int(cur.fetchone()["next_id"]) <= maximum:
                                        raise ValueError("Identity sequence not advanced")

                        # Apply the original foreign keys AFTER all tables and
                        # data exist; rejected orphan rows cause a full rollback.
                        for statement in foreign_keys:
                            cur.execute(statement)

                        # Compare all 26 source/restored table counts and
                        # physical column metadata while restore is still in
                        # the transaction. The existing loop below additionally
                        # checks *every row*, primary keys and child FKs.
                        with connection.cursor(row_factory=tuple_row) as base_cur:
                            restore_baseline = capture_legacy_baseline_on_cursor(
                                base_cur, schema=_RESTORE_SCHEMA
                            )
                        comparison = compare_isolated_restore_baselines(
                            source_baseline, restore_baseline
                        )
                        if comparison["status"] != "review_required":
                            raise ValueError("Restore baseline drift")

                        for name in names:
                            sort_col = "setting_key" if name == "system_settings" else "id"
                            cur.execute(
                                sql.SQL('SELECT * FROM {} ORDER BY {}').format(
                                    sql.Identifier(name), sql.Identifier(sort_col),
                                )
                            )
                            actual = [dict(row) for row in cur.fetchall()]
                            # JSON-safe normalized values are identical to the
                            # original export serialization for all supported
                            # primitive column types.
                            normalized = json.loads(json.dumps(
                                actual, default=str, ensure_ascii=False
                            ))
                            if normalized != batches[name]:
                                raise ValueError("Restore roundtrip mismatch")
                        # A SUCCESSFUL verification must also roll back, not
                        # leave any schema/data in the disposable CI database.
                        raise _VerifiedRollback()
            except _VerifiedRollback:
                return "verified", {
                    "tables": len(names),
                    "rows": restored_rows,
                    "rolled_back": True,
                    "schema_counts_match": True,
                    "provider_restore_verified": False,
                }
    except Exception:
        return "failed", None
    return "failed", None


def verify_disposable_encrypted_restore(url, ciphertext, passphrase):
    """CI-local, in-memory AES -> ZIP -> PostgreSQL -> rollback rehearsal.

    Reject *every* non-CI-local destination BEFORE decrypting the encrypted
    file. This does NOT check a real Supabase backup or perform a provider
    restore. Only synthetic disposable CI data are authorized for this test.
    """
    if not _ci_database_url_only(url):
        return "forbidden", None
    # Avoid a circular import: encrypted_backup -> backup_verify ->
    # postgres_restore_drill. Import only after the destination guard.
    from scripts.postgres_encrypted_backup import decrypt_export_zip

    decrypt_status, archive = decrypt_export_zip(ciphertext, passphrase)
    if decrypt_status != "decrypted":
        return "invalid_encrypted_archive", None
    status, report = verify_disposable_backup_restore(url, archive)
    if status != "verified" or not report or not report.get("rolled_back"):
        return "failed", None
    return "verified", {
        "tables": report["tables"],
        "rows": report["rows"],
        "rolled_back": True,
        "production_supabase_restore_verified": False,
    }
