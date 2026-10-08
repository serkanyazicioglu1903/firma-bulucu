"""Tests for Streamlit SQLite snapshot downloads, using only fictional data."""
import sqlite3
from pathlib import Path
import tempfile
import unittest

from security_admin import verified_sqlite_backup_bytes


class SQLiteDownloadTests(unittest.TestCase):
    def test_verified_backup_contains_rows_and_is_valid_sqlite(self):
        with tempfile.TemporaryDirectory() as folder:
            source = Path(folder) / "live.db"
            destination = Path(folder) / "downloaded.db"
            with sqlite3.connect(source) as conn:
                conn.execute("PRAGMA journal_mode=WAL")
                conn.execute("CREATE TABLE customers (id INTEGER PRIMARY KEY, name TEXT)")
                conn.execute("INSERT INTO customers VALUES (1, 'Example')")
            data = verified_sqlite_backup_bytes(source)
            self.assertTrue(data.startswith(b"SQLite format 3\\x00"))
            self.assertGreater(len(data), 100)
            destination.write_bytes(data)
            with sqlite3.connect(destination) as conn:
                self.assertEqual(conn.execute("PRAGMA integrity_check").fetchone()[0], "ok")
                self.assertEqual(conn.execute("SELECT name FROM customers").fetchone()[0], "Example")

    def test_missing_source_fails_without_creating_db(self):
        with tempfile.TemporaryDirectory() as folder:
            missing = Path(folder) / "missing.db"
            with self.assertRaises(FileNotFoundError):
                verified_sqlite_backup_bytes(missing)
            self.assertFalse(missing.exists())


if __name__ == "__main__":
    unittest.main()
