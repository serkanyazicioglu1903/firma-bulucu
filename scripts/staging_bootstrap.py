"""Guarded PostgreSQL staging-only schema bootstrap.

No source data is copied. Never call this from an automatic app startup path.
Only the existing ct_staging schema may be modified, and only if no application
tables already exist. Every CREATE/ALTER runs in one transaction.
"""
from urllib.parse import urlsplit

from scripts.build_pg_schema import (
    create_table_sql,
    foreign_key_sql,
    sqlite_schema,
)


SCHEMA = "ct_staging"
ALLOWED_PREEXISTING = frozenset({"migration_check"})


def classify_existing_tables(existing, expected):
    """Reject partial, unknown or conflicting staging schemas."""
    actual = set(existing)
    wanted = set(expected)
    if actual == wanted or actual == wanted | ALLOWED_PREEXISTING:
        return "already_present"
    if actual <= ALLOWED_PREEXISTING:
        return "create"
    return "conflict"


def bootstrap_staging(url):
    """Create empty staging tables only, returning a sanitized status and count.

    Never returns passwords, raw exceptions, SQL data or connection strings.
    """
    if not url or not str(url).strip():
        return "missing", 0
    try:
        parsed = urlsplit(str(url).strip())
        if parsed.scheme not in ("postgresql", "postgres") or not parsed.hostname:
            return "invalid_url", 0
    except ValueError:
        return "invalid_url", 0

    try:
        import psycopg

        # The checked-in schema is authoritative; do not read the user's SQLite data.
        with sqlite_schema() as source:
            expected = [
                row[0] for row in source.execute(
                    "SELECT name FROM sqlite_master WHERE type='table' "
                    "AND name NOT LIKE 'sqlite_%' ORDER BY rowid"
                )
            ]
            with psycopg.connect(
                str(url).strip(), connect_timeout=8, sslmode="require", autocommit=True
            ) as conn:
                with conn.transaction():
                    with conn.cursor() as cur:
                        cur.execute("SET LOCAL statement_timeout = '20s'")
                        cur.execute("SET LOCAL lock_timeout = '3s'")
                        cur.execute(
                            "SELECT 1 FROM pg_catalog.pg_namespace WHERE nspname = %s",
                            (SCHEMA,),
                        )
                        if cur.fetchone() is None:
                            return "schema_missing", 0

                        cur.execute(
                            "SELECT c.relname FROM pg_catalog.pg_class AS c "
                            "JOIN pg_catalog.pg_namespace AS n ON n.oid = c.relnamespace "
                            "WHERE n.nspname = %s AND c.relkind IN ('r', 'p')",
                            (SCHEMA,),
                        )
                        existing = [row[0] for row in cur.fetchall()]
                        decision = classify_existing_tables(existing, expected)
                        if decision != "create":
                            return decision, len(set(existing) & set(expected))

                        cur.execute('SET LOCAL search_path TO "ct_staging", pg_catalog')
                        for table in expected:
                            cur.execute(create_table_sql(source, table))
                        for table in expected:
                            for statement in foreign_key_sql(source, table):
                                cur.execute(statement)

                        cur.execute(
                            "SELECT c.relname FROM pg_catalog.pg_class AS c "
                            "JOIN pg_catalog.pg_namespace AS n ON n.oid = c.relnamespace "
                            "WHERE n.nspname = %s AND c.relkind IN ('r', 'p')",
                            (SCHEMA,),
                        )
                        after = {row[0] for row in cur.fetchall()}
                        if not set(expected).issubset(after):
                            raise RuntimeError("staging verification failed")
                        return "created", len(expected)
    except Exception:
        # The transaction rolls back on failure. Do not leak URI/passwords.
        return "failed", 0
