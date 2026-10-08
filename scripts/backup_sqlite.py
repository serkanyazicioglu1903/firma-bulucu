"""Create a verified, local, consistent SQLite snapshot before PostgreSQL staging work.

OFFLINE ONLY. Does not connect to PostgreSQL or modify the source database.
Usage: python scripts/backup_sqlite.py --source as_control_tower.db --dest /secure/backups/ct-20261008.sqlite3
Store the resulting database and manifest securely; both contain business-sensitive metadata/data.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import tempfile
from datetime import datetime, timezone
from urllib.parse import quote


def table_counts(conn):
    tables = [row[0] for row in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name"
    )]
    # Names originate from sqlite_master, but still quote them safely.
    return {name: conn.execute('SELECT COUNT(*) FROM "' + name.replace('"', '""') + '"').fetchone()[0]
            for name in tables}


def create_snapshot(source_path, destination_path):
    source = Path(source_path).expanduser().resolve(strict=True)
    dest = Path(destination_path).expanduser().absolute()
    if not source.is_file() or not source.name:
        raise ValueError("Source must be an existing SQLite database file.")
    if source == dest.resolve() or dest.exists() or dest.with_suffix(dest.suffix + ".json").exists():
        raise FileExistsError("Refusing to overwrite source, backup, or backup manifest.")
    if not dest.parent.is_dir():
        raise FileNotFoundError("Create the private backup directory before running this tool.")

    temporary = None
    manifest_path = dest.with_suffix(dest.suffix + ".json")
    try:
        fd, temporary = tempfile.mkstemp(prefix=".ct-backup-", suffix=".sqlite3", dir=dest.parent)
        os.fchmod(fd, 0o600)
        os.close(fd)
        uri = "file:" + quote(str(source), safe="/") + "?mode=ro"
        with sqlite3.connect(uri, uri=True) as original, sqlite3.connect(temporary) as snapshot:
            original.backup(snapshot)
        with sqlite3.connect(temporary) as verified:
            integrity = verified.execute("PRAGMA integrity_check").fetchone()[0]
            if integrity != "ok":
                raise RuntimeError("Backup integrity check failed.")
            counts = table_counts(verified)
        digest = hashlib.sha256()
        with open(temporary, "rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
        manifest = {
            "created_at_utc": datetime.now(timezone.utc).isoformat(),
            "backup_filename": dest.name,
            "sha256": digest.hexdigest(),
            "integrity_check": integrity,
            "table_counts": counts,
        }
        # Atomic create: a pre-existing backup is never replaced, even under a race.
        os.link(temporary, dest)
        try:
            with open(manifest_path, "x", encoding="utf-8") as handle:
                json.dump(manifest, handle, ensure_ascii=False, indent=2, sort_keys=True)
        except Exception:
            dest.unlink()
            raise
        return manifest
    finally:
        if temporary and Path(temporary).exists():
            Path(temporary).unlink()


def main():
    parser = argparse.ArgumentParser(description="Offline SQLite backup with integrity verification")
    parser.add_argument("--source", required=True, type=Path)
    parser.add_argument("--dest", required=True, type=Path)
    args = parser.parse_args()
    result = create_snapshot(args.source, args.dest)
    print("Verified SQLite backup:", args.dest)
    print("Tables:", len(result["table_counts"]), "SHA256:", result["sha256"])
    print("No PostgreSQL connection or cutover performed.")


if __name__ == "__main__":
    main()
