"""Read-only, repeatable-read export of the 26-table ct_app business database.

Exported ZIP includes private customer and financial data. Never log its content
and only offer it to an authenticated ADMIN from a direct button click.
No network service or local disk receives the ZIP. This is a supplement to,
not a replacement for, provider-managed encrypted backups.
"""
from datetime import datetime, timezone
from io import BytesIO
import hashlib
import json
import zipfile

from scripts.build_pg_schema import sqlite_schema
from scripts.postgres_connection import sslmode_for
from scripts.staging_transaction_smoke import validate_test_url
from scripts.staging_validate import validate_staging_structure
from scripts.postgres_company_migration_guard import company_schema_status_on_cursor

MAX_ROWS_PER_TABLE = 100_000
MAX_UNCOMPRESSED = 30 * 1024 * 1024


def export_postgres_backup(url):
    if not validate_test_url(url):
        return "invalid_url", None
    try:
        status, _ = validate_staging_structure(url, schema="ct_app")
        if status != "ok":
            return "schema_mismatch", None

        import psycopg
        from psycopg import sql
        from psycopg.rows import dict_row, tuple_row

        with sqlite_schema() as definitions:
            tables = [
                row[0] for row in definitions.execute(
                    "SELECT name FROM sqlite_master WHERE type='table' "
                    "AND name NOT LIKE 'sqlite_%' ORDER BY name"
                )
            ]
        if len(tables) != 26 or len(set(tables)) != 26:
            return "schema_mismatch", None

        output = BytesIO()
        manifest = {
            "format": "as-control-tower-ct-app-export-v1",
            "schema": "ct_app",
            "captured_utc": datetime.now(timezone.utc).isoformat(),
            "tables": {},
        }
        total_bytes = 0
        with psycopg.connect(
            str(url).strip(), connect_timeout=8, sslmode=sslmode_for(url),
            autocommit=True, row_factory=dict_row,
        ) as conn:
            with conn.transaction():
                with conn.cursor() as cur:
                    cur.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
                    cur.execute("SET LOCAL statement_timeout = '40s'")
                    cur.execute("SET LOCAL lock_timeout = '3s'")
                    # Legacy export contains exactly 26 original tables.
                    # Once ownership/grant migrations start it would omit
                    # new company registry and permissions. Never present
                    # this ZIP as a restorable, complete group-company backup.
                    # The existing export cursor has dict_row for ZIP
                    # serialization. Metadata checking deliberately uses
                    # tuple_row for predictable (row[0], bool tuple) results.
                    with conn.cursor(row_factory=tuple_row) as scope_cur:
                        if company_schema_status_on_cursor(scope_cur) != "legacy_schema_only":
                            return "company_scope_unsupported", None
                    with zipfile.ZipFile(
                        output, mode="w", compression=zipfile.ZIP_DEFLATED,
                    ) as archive:
                        for table in tables:
                            cur.execute(
                                sql.SQL("SELECT COUNT(*) AS n FROM {}").format(
                                    sql.Identifier("ct_app", table)
                                )
                            )
                            count = int(cur.fetchone()["n"])
                            if count > MAX_ROWS_PER_TABLE:
                                return "size_limit", None
                            cur.execute(
                                sql.SQL("SELECT * FROM {} ORDER BY id").format(
                                    sql.Identifier("ct_app", table)
                                ) if table != "system_settings" else
                                sql.SQL("SELECT * FROM {} ORDER BY setting_key").format(
                                    sql.Identifier("ct_app", table)
                                )
                            )
                            rows = cur.fetchall()
                            data = json.dumps(
                                rows, default=str, ensure_ascii=False,
                                separators=(",", ":"),
                            ).encode("utf-8")
                            total_bytes += len(data)
                            if total_bytes > MAX_UNCOMPRESSED:
                                return "size_limit", None
                            filename = "tables/" + table + ".json"
                            archive.writestr(filename, data)
                            manifest["tables"][table] = {
                                "row_count": count,
                                "sha256": hashlib.sha256(data).hexdigest(),
                            }
                        archive.writestr(
                            "manifest.json",
                            json.dumps(manifest, ensure_ascii=False, indent=2),
                        )
        return "ok", output.getvalue()
    except Exception:
        # DB errors and row contents may contain sensitive data.
        return "failed", None
