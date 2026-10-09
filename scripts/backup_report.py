"""Generate a non-sensitive, verifiable JSON manifest for a SQLite snapshot.

This module works on snapshot bytes and never connects to PostgreSQL or
changes the live SQLite database. The manifest belongs alongside the exact
snapshot downloaded in the same session.
"""
from datetime import datetime, timezone
import hashlib
from pathlib import Path
import sqlite3
import tempfile
from urllib.parse import quote

from scripts.backup_sqlite import table_counts


def build_backup_manifest(snapshot_bytes, filename):
    """Validate snapshot and describe it without reading out business rows.

    Foreign-key violations are reported but do not prevent preserving a copy:
    a problematic live database still needs a backup for recovery. A staging
    importer must refuse such backups until the issue is investigated.
    """
    if (not isinstance(snapshot_bytes, bytes)
            or not snapshot_bytes.startswith(b"SQLite format 3\x00")
            or not filename.endswith((".db", ".sqlite3"))
            or Path(filename).name != filename):
        raise ValueError("A real SQLite snapshot and its filename are required.")

    with tempfile.TemporaryDirectory(prefix="ct-verify-backup-") as folder:
        path = Path(folder) / "verify.sqlite3"
        path.write_bytes(snapshot_bytes)
        uri = "file:" + quote(str(path), safe="/") + "?mode=ro&immutable=1"
        with sqlite3.connect(uri, uri=True) as conn:
            conn.execute("PRAGMA query_only=ON")
            integrity = conn.execute("PRAGMA integrity_check").fetchone()[0]
            if integrity != "ok":
                raise ValueError("Backup integrity check failed.")
            fk_status = ("ok" if conn.execute("PRAGMA foreign_key_check").fetchone()
                         is None else "failed")
            counts = table_counts(conn)

    return {
        "backup_filename": filename,
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "sha256": hashlib.sha256(snapshot_bytes).hexdigest(),
        "integrity_check": "ok",
        "foreign_key_check": fk_status,
        "byte_size": len(snapshot_bytes),
        "table_counts": counts,
    }
