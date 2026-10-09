"""Offline safety checks for the backup-verified staging importer."""
from contextlib import contextmanager
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from scripts.backup_sqlite import create_snapshot
from scripts.staging_import import (
    MigrationSafetyError,
    _dependency_order,
    offline_preflight,
)


DDL = """
CREATE TABLE customers(
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE
);
CREATE TABLE orders(
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    customer_id INTEGER NOT NULL,
    amount REAL NOT NULL,
    FOREIGN KEY(customer_id) REFERENCES customers(id)
);
CREATE TABLE settings(setting_key TEXT PRIMARY KEY, setting_value TEXT);
"""


@contextmanager
def expected_schema():
    conn = sqlite3.connect(":memory:")
    try:
        conn.executescript(DDL)
        yield conn
    finally:
        conn.close()


class StagingImportOfflineTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        root = Path(self.directory.name)
        self.source = root / "live.db"
        self.backup = root / "verified.sqlite3"
        with sqlite3.connect(self.source) as conn:
            conn.executescript(DDL)
            conn.execute("INSERT INTO customers (name) VALUES ('Example')")
            conn.execute("INSERT INTO orders (customer_id, amount) VALUES (1, 15.25)")
            conn.execute("INSERT INTO settings VALUES ('sample', 'value')")

    def snapshot(self):
        create_snapshot(self.source, self.backup)
        return self.backup

    def test_verified_backup_is_offline_and_dependency_ordered(self):
        self.snapshot()
        with patch("scripts.staging_import.sqlite_schema", expected_schema):
            report = offline_preflight(self.backup)
        self.assertEqual(report["tables"], 3)
        self.assertEqual(report["rows"], 3)
        self.assertLess(report["order"].index("customers"),
                        report["order"].index("orders"))

    def test_modification_after_backup_invalidates_sha(self):
        self.snapshot()
        with sqlite3.connect(self.backup) as conn:
            conn.execute("UPDATE customers SET name='Changed'")
        with patch("scripts.staging_import.sqlite_schema", expected_schema):
            with self.assertRaises(MigrationSafetyError):
                offline_preflight(self.backup)

    def test_changed_manifest_counts_are_rejected(self):
        self.snapshot()
        manifest = Path(str(self.backup) + ".json")
        info = json.loads(manifest.read_text(encoding="utf-8"))
        info["table_counts"]["customers"] = 999
        manifest.write_text(json.dumps(info), encoding="utf-8")
        with patch("scripts.staging_import.sqlite_schema", expected_schema):
            with self.assertRaises(MigrationSafetyError):
                offline_preflight(self.backup)

    def test_unapproved_tables_are_rejected(self):
        with sqlite3.connect(self.source) as conn:
            conn.execute("CREATE TABLE extra (id INTEGER PRIMARY KEY)")
        self.snapshot()
        with patch("scripts.staging_import.sqlite_schema", expected_schema):
            with self.assertRaises(MigrationSafetyError):
                offline_preflight(self.backup)

    def test_broken_foreign_keys_are_rejected(self):
        with sqlite3.connect(self.source) as conn:
            conn.execute("PRAGMA foreign_keys=OFF")
            conn.execute("UPDATE orders SET customer_id=999")
        self.snapshot()
        with patch("scripts.staging_import.sqlite_schema", expected_schema):
            with self.assertRaises(MigrationSafetyError):
                offline_preflight(self.backup)

    def test_source_must_be_verified_backup_not_live_db(self):
        with patch("scripts.staging_import.sqlite_schema", expected_schema):
            with self.assertRaises(MigrationSafetyError):
                offline_preflight(self.source)

    def test_reject_cyclic_dependencies(self):
        conn = sqlite3.connect(":memory:")
        try:
            conn.executescript("""
                CREATE TABLE x(id INTEGER PRIMARY KEY, y_id INTEGER REFERENCES y(id));
                CREATE TABLE y(id INTEGER PRIMARY KEY, x_id INTEGER REFERENCES x(id));
            """)
            with self.assertRaises(MigrationSafetyError):
                _dependency_order(conn, {"x", "y"})
        finally:
            conn.close()


if __name__ == "__main__":
    unittest.main()
