import os
import sqlite3
from pathlib import Path

import pandas as pd
from sqlalchemy import create_engine, inspect

SQLITE_PATH = Path(os.getenv("SQLITE_PATH", "as_control_tower.db"))
DATABASE_URL = os.getenv("DATABASE_URL", "").strip()

SKIP_TABLES = {"sqlite_sequence"}


def main():
    if not SQLITE_PATH.exists():
        raise SystemExit(f"SQLite database not found: {SQLITE_PATH}")
    if not DATABASE_URL:
        raise SystemExit("DATABASE_URL is required.")

    engine = create_engine(DATABASE_URL, future=True)

    with sqlite3.connect(SQLITE_PATH) as source:
        tables = [
            row[0]
            for row in source.execute(
                "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
            ).fetchall()
            if row[0] not in SKIP_TABLES and not row[0].startswith("sqlite_")
        ]

        print(f"Found {len(tables)} SQLite tables.")
        for table in tables:
            df = pd.read_sql_query(f'SELECT * FROM "{table}"', source)
            print(f"{table}: {len(df)} rows")
            df.to_sql(
                table,
                engine,
                if_exists="replace",
                index=False,
                method="multi",
                chunksize=500,
            )

    inspector = inspect(engine)
    remote_tables = set(inspector.get_table_names())
    missing = [t for t in tables if t not in remote_tables]
    if missing:
        raise SystemExit(f"Migration incomplete. Missing tables: {missing}")

    print("SQLite -> PostgreSQL data copy completed.")
    print(
        "IMPORTANT: to_sql creates data tables but does not recreate all production "
        "constraints/indexes. Validate schema and backups before application cutover."
    )


if __name__ == "__main__":
    main()
