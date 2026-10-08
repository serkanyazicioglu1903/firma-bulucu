"""Deprecated unsafe importer.

The previous version used pandas.to_sql(if_exists="replace"), which could drop
existing PostgreSQL tables and remove constraints. Never run it against Supabase.
Migration must use reviewed, non-destructive staging import with reconciliation.
"""


def main():
    raise SystemExit(
        "BLOCKED: the legacy SQLite -> PostgreSQL importer used destructive "
        "if_exists='replace'. Use scripts/backup_sqlite.py to make a verified "
        "offline snapshot first, then follow POSTGRES_STAGING_PLAN.md. "
        "No database was changed."
    )


if __name__ == "__main__":
    main()
