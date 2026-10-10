"""Read-only PostgreSQL staging cutover readiness audit.

Compares the *active local SQLite schema* with the approved definitions and
checks that all 26 ct_staging PostgreSQL tables exist and are empty.
No business rows, passwords or SQL exceptions are returned to Streamlit.
This is preparation only: neither records nor application storage are moved.
"""
from pathlib import Path
import sqlite3
from urllib.parse import quote

from scripts.staging_import import _check_layout, _quoted
from scripts.staging_transaction_smoke import validate_test_url
from scripts.staging_validate import validate_staging_structure

SCHEMA = "ct_staging"


def read_sqlite_source_counts(db_path):
    """Read only a consistent SQLite transaction, not a file copy."""
    path = Path(db_path).expanduser().resolve()
    if not path.is_file():
        raise ValueError("Source SQLite database is missing.")
    uri = "file:" + quote(str(path), safe="/") + "?mode=ro"
    with sqlite3.connect(uri, uri=True, timeout=5) as source:
        source.execute("PRAGMA query_only=ON")
        source.execute("BEGIN")
        if source.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
            raise ValueError("SQLite source integrity failed.")
        if source.execute("PRAGMA foreign_key_check").fetchone() is not None:
            raise ValueError("SQLite source foreign keys failed.")
        tables = _check_layout(source)
        return {table: int(source.execute(
            "SELECT COUNT(*) FROM " + _quoted(table)
        ).fetchone()[0]) for table in tables}


def read_postgres_target_counts(url, tables):
    """Read table counts using a read-only PostgreSQL transaction."""
    import psycopg
    from psycopg import sql

    with psycopg.connect(
        str(url).strip(), connect_timeout=8, sslmode="require",
    ) as connection:
        with connection.cursor() as cur:
            cur.execute("SET TRANSACTION READ ONLY")
            cur.execute("SET LOCAL statement_timeout = '20s'")
            cur.execute("SET LOCAL lock_timeout = '3s'")
            result = {}
            for table in tables:
                if not table.isidentifier() or table.lower() != table:
                    raise ValueError("Unexpected table name.")
                cur.execute(sql.SQL("SELECT COUNT(*) FROM {}").format(
                    sql.Identifier(SCHEMA, table)
                ))
                result[table] = int(cur.fetchone()[0])
            return result


def assess_migration_readiness(db_path, staging_url):
    """Return sanitized counts and a safe fail-closed readiness result.

    status: invalid_url | schema_failed | sqlite_failed | postgres_failed |
            target_not_empty | ready_for_staging_import
    The result intentionally contains neither raw data nor connection details.
    """
    result = {"status": "invalid_url", "source_tables": 0,
              "source_rows": 0, "target_tables": 0, "target_rows": 0}
    if not validate_test_url(staging_url):
        return result
    result["status"] = "schema_failed"
    try:
        status, _issues = validate_staging_structure(staging_url)
        if status != "ok":
            return result
    except Exception:
        return result
    result["status"] = "sqlite_failed"
    try:
        source_counts = read_sqlite_source_counts(db_path)
        result["source_tables"] = len(source_counts)
        result["source_rows"] = sum(source_counts.values())
    except Exception:
        return result
    result["status"] = "postgres_failed"
    try:
        target_counts = read_postgres_target_counts(
            staging_url, sorted(source_counts)
        )
        if set(target_counts) != set(source_counts):
            return result
        result["target_tables"] = len(target_counts)
        result["target_rows"] = sum(target_counts.values())
    except Exception:
        return result
    result["status"] = (
        "ready_for_staging_import"
        if result["target_rows"] == 0 else "target_not_empty"
    )
    return result
