"""Opt-in creation of a *separate* PostgreSQL application schema.

ct_staging stays a disposable test sandbox. ct_app is reserved for eventual
durable operational storage, but creating the schema does NOT switch any
Streamlit module away from SQLite. No company records are imported here.
Nothing is executed on import, startup, or through the read-only status call.
"""
from scripts.build_pg_schema import (
    sqlite_schema, create_table_sql, foreign_key_sql, quote,
)
from scripts.staging_transaction_smoke import validate_test_url
from scripts.staging_validate import validate_staging_structure

LIVE_SCHEMA = "ct_app"
EXPLICIT_CONFIRMATION = "CREATE_NEW_EMPTY_CT_APP"


def schema_ddl_steps():
    """Offline, fixed-schema plan from checked-in, audited SQLite definitions."""
    with sqlite_schema() as connection:
        names = [
            row[0] for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table' "
                "AND name NOT LIKE 'sqlite_%' ORDER BY rowid"
            )
        ]
        if len(names) != 26 or len(set(names)) != 26:
            raise ValueError("Expected exactly 26 application tables.")
        table_sql = [create_table_sql(connection, table) for table in names]
        fk_sql = []
        for table in names:
            fk_sql.extend(foreign_key_sql(connection, table))
        return names, table_sql, fk_sql


def read_live_schema_status(url):
    """Read-only status, with no passwords, hostnames or business rows."""
    if not validate_test_url(url):
        return "invalid_url"
    try:
        import psycopg
        with psycopg.connect(
            str(url).strip(), connect_timeout=8, sslmode="require"
        ) as connection:
            with connection.cursor() as cur:
                cur.execute("SET TRANSACTION READ ONLY")
                cur.execute(
                    "SELECT EXISTS (SELECT 1 FROM pg_namespace WHERE nspname=%s)",
                    (LIVE_SCHEMA,),
                )
                found = bool(cur.fetchone()[0])
        if not found:
            return "not_created"
        status, _ = validate_staging_structure(url, schema=LIVE_SCHEMA)
        return "ready" if status == "ok" else "schema_mismatch"
    except Exception:
        return "failed"


def provision_live_schema(url, confirmation=""):
    """Atomically create ct_app only when completely absent and approved.

    Returns: confirmation_required | invalid_url | exists | created | failed.
    Never drops, modifies, or imports existing business records.
    """
    if confirmation != EXPLICIT_CONFIRMATION:
        return "confirmation_required"
    if not validate_test_url(url):
        return "invalid_url"
    try:
        _, tables, foreign_keys = schema_ddl_steps()
        import psycopg
        with psycopg.connect(
            str(url).strip(), connect_timeout=8, sslmode="require",
            autocommit=True,
        ) as connection:
            with connection.transaction():
                with connection.cursor() as cur:
                    cur.execute("SET LOCAL statement_timeout = '30s'")
                    cur.execute("SET LOCAL lock_timeout = '3s'")
                    cur.execute(
                        "SELECT EXISTS (SELECT 1 FROM pg_namespace WHERE nspname=%s)",
                        (LIVE_SCHEMA,),
                    )
                    if bool(cur.fetchone()[0]):
                        # Fail before any write to an existing schema.
                        return "exists"
                    cur.execute("CREATE SCHEMA " + quote(LIVE_SCHEMA))
                    cur.execute(
                        "SET LOCAL search_path TO " + quote(LIVE_SCHEMA) + ", pg_catalog"
                    )
                    for statement in tables:
                        cur.execute(statement)
                    for statement in foreign_keys:
                        cur.execute(statement)
    except Exception:
        # Never echo PostgreSQL exception (could contain credentials).
        return "failed"
    status, _ = validate_staging_structure(url, schema=LIVE_SCHEMA)
    return "created" if status == "ok" else "failed"
