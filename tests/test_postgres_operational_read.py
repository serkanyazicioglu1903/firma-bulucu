"""Offline regression tests for read-only ct_app PostgreSQL backend."""
import unittest
from unittest.mock import MagicMock, patch

from scripts import postgres_operational_read as operational


FAKE_URL = "postgresql://user:private-password@host/db"


class OperationalBackendReadTests(unittest.TestCase):
    def test_requires_postgres_uri_without_connections(self):
        with patch.object(operational, "validate_staging_structure") as validate:
            status, data = operational.read_operational_counts("sqlite://local/file")
            self.assertEqual((status, data), ("invalid_url", {}))
            validate.assert_not_called()

    @patch.object(operational, "validate_staging_structure", return_value=("mismatch", []))
    @patch("psycopg.connect")
    def test_schema_check_blocks_reads(self, connect, validate):
        self.assertEqual(
            operational.read_operational_counts(FAKE_URL),
            ("schema_mismatch", {}),
        )
        validate.assert_called_once_with(FAKE_URL, schema="ct_app")
        connect.assert_not_called()

    @patch.object(operational, "validate_staging_structure", return_value=("ok", []))
    @patch("psycopg.connect")
    def test_reads_only_aggregate_counts_in_transaction(self, connect, validate):
        cur = MagicMock()
        cur.fetchone.side_effect = [(i,) for i in range(len(operational.TABLES))]
        connect.return_value.__enter__.return_value.cursor.return_value.__enter__.return_value = cur
        status, counts = operational.read_operational_counts(FAKE_URL)
        self.assertEqual(status, "ok")
        self.assertEqual(len(counts), len(operational.TABLES))
        self.assertEqual(counts["customers"], 0)
        self.assertEqual(counts["finance_transactions"], len(operational.TABLES) - 1)
        statements = cur.execute.call_args_list
        self.assertEqual(statements[0].args[0], "SET TRANSACTION READ ONLY")
        self.assertEqual(len(statements), len(operational.TABLES) + 3)
        for call in statements[3:]:
            self.assertIn("SELECT COUNT(*)", str(call.args[0]))
            self.assertNotIn("DELETE", str(call.args[0]))
            self.assertNotIn("UPDATE", str(call.args[0]))
        self.assertNotIn("private-password", str(counts))
        validate.assert_called_once_with(FAKE_URL, schema="ct_app")

    @patch.object(operational, "validate_staging_structure", return_value=("ok", []))
    @patch("psycopg.connect", side_effect=RuntimeError("password private-password"))
    def test_exception_never_leaks_secrets(self, *_):
        status, values = operational.read_operational_counts(FAKE_URL)
        self.assertEqual((status, values), ("failed", {}))
        self.assertNotIn("private-password", str((status, values)))


if __name__ == "__main__":
    unittest.main()
