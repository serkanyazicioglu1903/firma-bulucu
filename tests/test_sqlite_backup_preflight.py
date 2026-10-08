"""Offline backup safety tests; no live business data or Supabase credentials."""
import hashlib
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest

from scripts.backup_sqlite import create_snapshot


class BackupTests(unittest.TestCase):
    def test_verified_snapshot_preserves_rows_and_manifest(self):
        with tempfile.TemporaryDirectory() as folder:
            source = Path(folder) / "source.sqlite3"
            dest = Path(folder) / "backup.sqlite3"
            with sqlite3.connect(source) as conn:
                conn.execute("CREATE TABLE customers (id INTEGER PRIMARY KEY, name TEXT)")
                conn.execute("INSERT INTO customers VALUES (1, 'Demo')")
            result = create_snapshot(source, dest)
            self.assertEqual(result["table_counts"], {"customers": 1})
            self.assertEqual(result["integrity_check"], "ok")
            self.assertEqual(result["sha256"], hashlib.sha256(dest.read_bytes()).hexdigest())
            self.assertEqual(json.loads((Path(str(dest) + ".json")).read_text())["table_counts"], {"customers": 1})
            with sqlite3.connect(dest) as conn:
                self.assertEqual(conn.execute("SELECT name FROM customers").fetchone()[0], "Demo")
            with sqlite3.connect(source) as conn:
                self.assertEqual(conn.execute("SELECT name FROM customers").fetchone()[0], "Demo")

    def test_refuses_overwrite_and_source_as_destination(self):
        with tempfile.TemporaryDirectory() as folder:
            source = Path(folder) / "source.sqlite3"
            dest = Path(folder) / "backup.sqlite3"
            with sqlite3.connect(source) as conn:
                conn.execute("CREATE TABLE sample (value TEXT)")
            with self.assertRaises(FileExistsError):
                create_snapshot(source, source)
            create_snapshot(source, dest)
            with self.assertRaises(FileExistsError):
                create_snapshot(source, dest)

    def test_missing_source_does_not_create_backup(self):
        with tempfile.TemporaryDirectory() as folder:
            dest = Path(folder) / "backup.sqlite3"
            with self.assertRaises(FileNotFoundError):
                create_snapshot(Path(folder) / "missing.sqlite3", dest)
            self.assertFalse(dest.exists())


if __name__ == "__main__":
    unittest.main()
