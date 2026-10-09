"""Verified SQLite -> ct_staging import. NEVER switches the live application.

Default mode is offline preflight (no PostgreSQL connection or writes).
An import requires a verified backup manifest, a separate staging URL in the
STAGING_DATABASE_URL environment variable, and three explicit CLI flags.
All target writes and reconciliation run in one PostgreSQL transaction.
"""
import argparse
from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import sys
from urllib.parse import quote

from scripts.backup_sqlite import table_counts
from scripts.build_pg_schema import sqlite_schema
from scripts.staging_validate import validate_staging_structure

SCHEMA = "ct_staging"
CONFIRMATION = "CT_STAGING_ONLY"
BATCH_SIZE = 250


class MigrationSafetyError(Exception):
    """Deliberately excludes connection strings and business row content."""


def _quoted(name):
    return '"' + name.replace('"', '""') + '"'


def _digest(path):
    result = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            result.update(chunk)
    return result.hexdigest()


def _columns(conn, table):
    return conn.execute("PRAGMA table_info(" + _quoted(table) + ")").fetchall()


def _foreign_keys(conn, table):
    return conn.execute("PRAGMA foreign_key_list(" + _quoted(table) + ")").fetchall()


def _unique_keys(conn, table):
    keys = []
    for item in conn.execute("PRAGMA index_list(" + _quoted(table) + ")"):
        if item[3] == "u":
            keys.append(tuple(row[2] for row in conn.execute(
                "PRAGMA index_info(" + _quoted(item[1]) + ")"
            )))
    return sorted(keys)


def _check_layout(source):
    """Reject drift, unknown tables and source schema missing constraints."""
    with sqlite_schema() as expected:
        expected_tables = set(table_counts(expected))
        actual_tables = set(table_counts(source))
        if actual_tables != expected_tables:
            raise MigrationSafetyError("Unexpected or missing source tables.")
        for name in sorted(expected_tables):
            # Ignore default expression spelling; data is inserted explicitly.
            def signature(conn):
                return [(r[1], r[2].upper(), r[3], r[5])
                        for r in _columns(conn, name)]
            if signature(source) != signature(expected):
                raise MigrationSafetyError("Source columns differ from approved schema.")
            if _foreign_keys(source, name) != _foreign_keys(expected, name):
                raise MigrationSafetyError("Source foreign keys differ.")
            if _unique_keys(source, name) != _unique_keys(expected, name):
                raise MigrationSafetyError("Source unique constraints differ.")
        return _dependency_order(expected, expected_tables)


def _dependency_order(conn, tables):
    dependencies = {name: {row[2] for row in _foreign_keys(conn, name)}
                    for name in tables}
    for name, refs in dependencies.items():
        if not refs <= tables:
            raise MigrationSafetyError("Unknown foreign-key dependency.")
        if name in refs:
            raise MigrationSafetyError("Self-referencing table needs separate review.")
    ordered, visiting, visited = [], set(), set()

    def visit(name):
        if name in visiting:
            raise MigrationSafetyError("Cyclic foreign keys need separate review.")
        if name in visited:
            return
        visiting.add(name)
        for dep in sorted(dependencies[name]):
            visit(dep)
        visiting.remove(name)
        visited.add(name)
        ordered.append(name)

    for name in sorted(tables):
        visit(name)
    return ordered


@contextmanager
def verified_snapshot(backup_path, manifest_path=None):
    """Open only a consistent, manifested SQLite backup, in read-only mode."""
    source = Path(backup_path).expanduser().resolve(strict=True)
    if not source.is_file() or source.suffix != ".sqlite3":
        raise MigrationSafetyError("Supply a .sqlite3 backup, not a live .db file.")
    manifest_path = (Path(manifest_path).expanduser().resolve(strict=True)
                     if manifest_path else Path(str(source) + ".json"))
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError) as exc:
        raise MigrationSafetyError("Backup manifest is missing or invalid.") from None
    if (manifest.get("backup_filename") != source.name
            or manifest.get("integrity_check") != "ok"
            or manifest.get("sha256") != _digest(source)):
        raise MigrationSafetyError("Backup manifest or SHA256 does not match.")
    uri = "file:" + quote(str(source), safe="/") + "?mode=ro&immutable=1"
    connection = None
    try:
        connection = sqlite3.connect(uri, uri=True)
        connection.execute("PRAGMA query_only=ON")
        if connection.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
            raise MigrationSafetyError("Backup integrity check failed.")
        if connection.execute("PRAGMA foreign_key_check").fetchone() is not None:
            raise MigrationSafetyError("Backup contains invalid foreign-key relations.")
        counts = table_counts(connection)
        if counts != manifest.get("table_counts"):
            raise MigrationSafetyError("Backup table counts differ from its manifest.")
        ordered = _check_layout(connection)
        yield connection, counts, ordered
    except sqlite3.Error:
        raise MigrationSafetyError("Cannot verify the SQLite backup.") from None
    finally:
        if connection is not None:
            connection.close()


def offline_preflight(backup_path, manifest_path=None):
    """No network, credentials or database writes. Returns counts, never rows."""
    with verified_snapshot(backup_path, manifest_path) as (_source, counts, order):
        return {"tables": len(order), "rows": sum(counts.values()),
                "order": order, "counts": counts}


def _order_clause(pg_sql, source, table):
    primary = sorted((r for r in _columns(source, table) if r[5]),
                     key=lambda r: r[5])
    if not primary:
        raise MigrationSafetyError("Cannot reconcile table without primary key.")
    sqlite_order = ", ".join(_quoted(r[1]) for r in primary)
    pg_order = pg_sql.SQL(", ").join(
        (pg_sql.SQL('{} COLLATE "C"').format(pg_sql.Identifier(r[1]))
         if r[2].upper() == "TEXT" else pg_sql.Identifier(r[1]))
        for r in primary
    )
    return sqlite_order, pg_order


def _copy_and_reconcile(pg, source, counts, order):
    """Single transaction: lock, assert empty, copy, check every row, sync IDs."""
    from psycopg import sql
    with pg.transaction():
        with pg.cursor() as cur:
            cur.execute("SET LOCAL statement_timeout = '120s'")
            cur.execute("SET LOCAL lock_timeout = '5s'")
            cur.execute('SET LOCAL search_path TO "ct_staging", pg_catalog')
            # Exclusive locks prevent races between the empty check and inserts.
            for table in sorted(order):
                ident = sql.Identifier(SCHEMA, table)
                cur.execute(sql.SQL("LOCK TABLE {} IN ACCESS EXCLUSIVE MODE").format(ident))
                cur.execute(sql.SQL("SELECT COUNT(*) FROM {}").format(ident))
                if cur.fetchone()[0] != 0:
                    raise MigrationSafetyError("Staging application tables are not empty.")

            for table in order:
                ident = sql.Identifier(SCHEMA, table)
                columns = [r[1] for r in _columns(source, table)]
                fields = sql.SQL(", ").join(map(sql.Identifier, columns))
                placeholders = sql.SQL(", ").join(sql.Placeholder() for _ in columns)
                insert = sql.SQL("INSERT INTO {} ({}) VALUES ({})").format(
                    ident, fields, placeholders
                )
                reader = source.execute("SELECT " + ", ".join(map(_quoted, columns))
                                        + " FROM " + _quoted(table))
                while True:
                    batch = reader.fetchmany(BATCH_SIZE)
                    if not batch:
                        break
                    cur.executemany(insert, batch)

                cur.execute(sql.SQL("SELECT COUNT(*) FROM {}").format(ident))
                if cur.fetchone()[0] != counts[table]:
                    raise MigrationSafetyError("Staging row count mismatch.")

                primary = sorted((r for r in _columns(source, table) if r[5]),
                                 key=lambda r: r[5])
                if (len(primary) == 1 and primary[0][1] == "id"
                        and primary[0][2].upper() == "INTEGER"):
                    cur.execute(sql.SQL("SELECT COALESCE(MAX(id),0) FROM {}").format(ident))
                    max_id = cur.fetchone()[0]
                    cur.execute("SELECT pg_get_serial_sequence(%s, %s)",
                                (SCHEMA + "." + table, "id"))
                    sequence = cur.fetchone()[0]
                    if not sequence:
                        raise MigrationSafetyError("Missing identity sequence.")
                    cur.execute("SELECT setval(%s::regclass, %s, %s)",
                                (sequence, max(max_id, 1), max_id > 0))

            # Verify every field in every record, not just table counts/totals.
            for table in order:
                columns = [r[1] for r in _columns(source, table)]
                fields = sql.SQL(", ").join(map(sql.Identifier, columns))
                sqlite_order, pg_order = _order_clause(sql, source, table)
                src = source.execute(
                    "SELECT " + ", ".join(map(_quoted, columns)) + " FROM "
                    + _quoted(table) + " ORDER BY " + sqlite_order
                )
                with pg.cursor(name="ct_verify_" + table) as reader:
                    reader.execute(sql.SQL("SELECT {} FROM {} ORDER BY {}").format(
                        fields, sql.Identifier(SCHEMA, table), pg_order
                    ))
                    while True:
                        batch = src.fetchmany(BATCH_SIZE)
                        if not batch:
                            if reader.fetchone() is not None:
                                raise MigrationSafetyError("Unexpected staging rows.")
                            break
                        target = reader.fetchmany(len(batch))
                        if len(target) != len(batch):
                            raise MigrationSafetyError("Missing staging rows.")
                        for left, right in zip(batch, target):
                            if tuple(left) != tuple(right):
                                raise MigrationSafetyError("Staging values differ.")
            # Transaction commits ONLY after the complete cross-table comparison.


def apply_staging_import(backup_path, manifest_path, dsn):
    if not dsn:
        raise MigrationSafetyError("STAGING_DATABASE_URL is required.")
    # No write, even in staging, unless read-only structural verification succeeds.
    status, _issues = validate_staging_structure(dsn)
    if status != "ok":
        raise MigrationSafetyError("Staging structure was not verified.")
    with verified_snapshot(backup_path, manifest_path) as (source, counts, order):
        import psycopg
        try:
            with psycopg.connect(dsn.strip(), connect_timeout=8, sslmode="require",
                                 autocommit=True) as pg:
                _copy_and_reconcile(pg, source, counts, order)
        except MigrationSafetyError:
            raise
        except Exception:
            # Never expose raw DB errors: they can include credentials or data.
            raise MigrationSafetyError("Staging import failed and was rolled back.") from None
        return {"tables": len(order), "rows": sum(counts.values())}


def main():
    parser = argparse.ArgumentParser(description="Verified, staging-only SQLite importer")
    parser.add_argument("--source", required=True, help="Verified private .sqlite3 backup")
    parser.add_argument("--manifest", help="Defaults to <source>.json")
    parser.add_argument("--apply", action="store_true", help="Opt in to a PostgreSQL write")
    parser.add_argument("--confirm-target", default="", help="Must equal CT_STAGING_ONLY")
    parser.add_argument("--confirm-source-reviewed", action="store_true",
                        help="I verified this is the intended, approved source snapshot")
    args = parser.parse_args()
    try:
        info = offline_preflight(args.source, args.manifest)
        print("Offline verified:", info["tables"], "tables;", info["rows"], "rows.")
        if not args.apply:
            print("DRY RUN ONLY. No PostgreSQL connection, no records copied.")
            return 0
        if args.confirm_target != CONFIRMATION or not args.confirm_source_reviewed:
            raise MigrationSafetyError("Explicit target and source confirmations required.")
        result = apply_staging_import(
            args.source, args.manifest, os.environ.get("STAGING_DATABASE_URL", "")
        )
        print("Staging import verified:", result["tables"], "tables;",
              result["rows"], "rows. Production SQLite remains unchanged.")
        return 0
    except (MigrationSafetyError, OSError, ValueError):
        print("Stopped safely: backup, permissions, or schema checks failed.",
              file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
