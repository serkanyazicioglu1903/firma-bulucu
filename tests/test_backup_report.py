"""Local-only checks for paired SQLite backup + manifest downloads."""
import hashlib
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from scripts.backup_report import build_backup_manifest
from scripts.staging_import import (
    MigrationSafetyError, offline_preflight
)


class BackupReportTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.root = Path(self.folder.name)
        self.db = self.root / "example.db"
        with sqlite3.connect(self.db) as conn:
            conn.executescript("""
                PRAGMA foreign_keys=ON;
                CREATE TABLE customers(id INTEGER PRIMARY KEY AUTOINCREMENT,
                                       name TEXT NOT NULL);
                CREATE TABLE orders(id INTEGER PRIMARY KEY AUTOINCREMENT,
                                    customer_id INTEGER REFERENCES customers(id));
                INSERT INTO customers (name) VALUES ('Fictional');
                INSERT INTO orders (customer_id) VALUES (1);
            """)

    def snapshot(self):
        return self.db.read_bytes()

    def test_report_has_exact_hash_and_sanitized_metadata(self):
        raw = self.snapshot()
        report = build_backup_manifest(raw, "private_backup.db")
        self.assertEqual(report["sha256"], hashlib.sha256(raw).hexdigest())
        self.assertEqual(report["integrity_check"], "ok")
        self.assertEqual(report["foreign_key_check"], "ok")
        self.assertEqual(report["byte_size"], len(raw))
        self.assertEqual(report["table_counts"], {"customers": 1, "orders": 1})
        self.assertNotIn("Fictional", json.dumps(report))

    def test_bad_backup_is_rejected(self):
        for data in (b"", b"File not found", b"SQLite format 3\x00bad"):
            with self.subTest(data=data):
                with self.assertRaises((ValueError, sqlite3.Error)):
                    build_backup_manifest(data, "example.db")

    def test_filename_must_be_basename(self):
        with self.assertRaises(ValueError):
            build_backup_manifest(self.snapshot(), "../../private.db")

    def test_foreign_key_violation_is_reported_without_erasing_backup(self):
        with sqlite3.connect(self.db) as conn:
            conn.execute("PRAGMA foreign_keys=OFF")
            conn.execute("UPDATE orders SET customer_id=98765")
        report = build_backup_manifest(self.snapshot(), "private_backup.db")
        self.assertEqual(report["foreign_key_check"], "failed")
        self.assertEqual(report["integrity_check"], "ok")

    def test_app_db_without_matching_manifest_cannot_enter_import_preflight(self):
        copied = self.root / "app_copy.db"
        copied.write_bytes(self.snapshot())
        with self.assertRaises(MigrationSafetyError):
            offline_preflight(copied)

    def test_matching_manifest_allows_importer_to_validate_db_source(self):
        copied = self.root / "app_copy.db"
        raw = self.snapshot()
        copied.write_bytes(raw)
        manifest = build_backup_manifest(raw, copied.name)
        Path(str(copied) + ".json").write_text(
            json.dumps(manifest), encoding="utf-8"
        )
        # A source schema check is still mandatory. It fails in this fixture
        # because the real app expects more tables than this tiny sample.
        with self.assertRaises(MigrationSafetyError) as ctx:
            offline_preflight(copied)
        self.assertIn("source tables", str(ctx.exception).lower())


if __name__ == "__main__":
    unittest.main()
