"""Offline coverage for read-only migration readiness and fail-closed gates."""
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from scripts import postgres_migration_readiness as readiness

FAKE_URL = "postgresql://hidden:private-password@localhost:5432/staging"


class MigrationReadinessTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.db = Path(self.tmp.name) / "source.db"
        with sqlite3.connect(self.db) as conn:
            conn.execute("PRAGMA foreign_keys=ON")
            conn.executescript(
                "CREATE TABLE customers(id INTEGER PRIMARY KEY,name TEXT);"
                "CREATE TABLE orders(id INTEGER PRIMARY KEY, customer_id INTEGER "
                "REFERENCES customers(id));"
                "INSERT INTO customers VALUES(1,'PRIVATE COMPANY');"
                "INSERT INTO orders VALUES(1,1);"
            )

    def test_only_approved_sqlite_tables_are_counted(self):
        with patch.object(readiness, "_check_layout", return_value=[
            "customers", "orders",
        ]):
            self.assertEqual(
                readiness.read_sqlite_source_counts(self.db),
                {"customers": 1, "orders": 1},
            )

    def test_nonexistent_source_never_creates_a_database(self):
        missing = self.db.parent / "never-created.db"
        with self.assertRaises(ValueError):
            readiness.read_sqlite_source_counts(missing)
        self.assertFalse(missing.exists())

    def test_source_integrity_blocks_broken_foreign_keys(self):
        with sqlite3.connect(self.db) as conn:
            conn.execute("UPDATE orders SET customer_id=999 WHERE id=1")
        with patch.object(readiness, "_check_layout", return_value=[
            "customers", "orders",
        ]):
            with self.assertRaises(ValueError):
                readiness.read_sqlite_source_counts(self.db)

    @patch.object(readiness, "validate_staging_structure", return_value=("ok", []))
    @patch.object(readiness, "read_sqlite_source_counts", return_value={
        "customers": 1, "orders": 1,
    })
    @patch.object(readiness, "read_postgres_target_counts", return_value={
        "customers": 0, "orders": 0,
    })
    def test_empty_staging_is_ready_but_not_migrated(self, _pg, _sqlite, _schema):
        report = readiness.assess_migration_readiness(self.db, FAKE_URL)
        self.assertEqual(report, {
            "status": "ready_for_staging_import",
            "source_tables": 2, "source_rows": 2,
            "target_tables": 2, "target_rows": 0,
        })
        self.assertNotIn("PRIVATE COMPANY", str(report))
        self.assertNotIn("private-password", str(report))

    @patch.object(readiness, "validate_staging_structure", return_value=("ok", []))
    @patch.object(readiness, "read_sqlite_source_counts", return_value={
        "customers": 0, "orders": 0,
    })
    @patch.object(readiness, "read_postgres_target_counts", return_value={
        "customers": 2, "orders": 0,
    })
    def test_nonempty_staging_blocks_import(self, *_):
        report = readiness.assess_migration_readiness(self.db, FAKE_URL)
        self.assertEqual(report["status"], "target_not_empty")
        self.assertEqual(report["target_rows"], 2)

    @patch.object(readiness, "validate_staging_structure", return_value=("mismatch", []))
    @patch.object(readiness, "read_sqlite_source_counts")
    def test_schema_mismatch_blocks_source_access(self, source, _schema):
        report = readiness.assess_migration_readiness(self.db, FAKE_URL)
        self.assertEqual(report["status"], "schema_failed")
        source.assert_not_called()

    @patch.object(readiness, "validate_staging_structure", return_value=("ok", []))
    @patch.object(readiness, "read_sqlite_source_counts", return_value={
        "customers": 1,
    })
    @patch.object(readiness, "read_postgres_target_counts", side_effect=RuntimeError(
        "password: private-password"
    ))
    def test_target_exception_is_sanitized(self, *_):
        report = readiness.assess_migration_readiness(self.db, FAKE_URL)
        self.assertEqual(report["status"], "postgres_failed")
        self.assertNotIn("private-password", str(report))

    @patch.object(readiness, "validate_staging_structure")
    def test_invalid_url_skips_network(self, schema):
        report = readiness.assess_migration_readiness(
            self.db, "sqlite:///no-connection.db",
        )
        self.assertEqual(report["status"], "invalid_url")
        schema.assert_not_called()

    @patch.object(readiness, "validate_staging_structure", return_value=("ok", []))
    @patch.object(readiness, "read_sqlite_source_counts", return_value={
        "customers": 0, "orders": 0,
    })
    @patch.object(readiness, "read_postgres_target_counts", return_value={
        "customers": 0,
    })
    def test_missing_postgres_table_blocks_readiness(self, *_):
        report = readiness.assess_migration_readiness(self.db, FAKE_URL)
        self.assertEqual(report["status"], "postgres_failed")


if __name__ == "__main__":
    unittest.main()
