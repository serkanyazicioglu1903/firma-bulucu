"""No-live-data tests for PostgreSQL operational reconciliation gates."""
import unittest
from unittest.mock import MagicMock, patch

from scripts import postgres_reconciliation as audit

FAKE_URL = "postgresql://operator:do-not-display-secret@localhost/db"


class OperationalReconciliationTests(unittest.TestCase):
    def test_definitions_are_fixed_and_aggregate_only(self):
        self.assertEqual(len(audit.CHECKS), 10)
        self.assertEqual(len({c[0] for c in audit.CHECKS}), 10)
        for machine_id, label, area, severity, query in audit.CHECKS:
            with self.subTest(check=machine_id):
                self.assertTrue(label and area)
                self.assertIn(severity, ("critical", "warning"))
                self.assertIn("SELECT COUNT(*)", query.upper())
                self.assertNotIn("SELECT *", query.upper())
                self.assertNotIn("INSERT INTO", query.upper())
                self.assertNotIn("UPDATE ", query.upper())
                self.assertNotIn("DELETE FROM", query.upper())

    @patch.object(audit, "validate_staging_structure")
    def test_invalid_url_stops_before_connections(self, schema):
        self.assertEqual(
            audit.check_operational_consistency("sqlite:///production.db"),
            {"status": "invalid_url", "checks": []},
        )
        schema.assert_not_called()

    @patch.object(audit, "validate_staging_structure", return_value=("mismatch", ["private"]))
    @patch("psycopg.connect")
    def test_schema_mismatch_stops_before_connecting(self, connect, schema):
        self.assertEqual(
            audit.check_operational_consistency(FAKE_URL),
            {"status": "schema_mismatch", "checks": []},
        )
        schema.assert_called_once_with(FAKE_URL, schema="ct_app")
        connect.assert_not_called()

    @patch.object(audit, "validate_staging_structure", return_value=("ok", []))
    @patch("psycopg.connect")
    def test_zero_anomalies_runs_all_checks_in_read_only_transaction(
        self, connect, schema,
    ):
        connection = connect.return_value.__enter__.return_value
        cur = connection.transaction.return_value.__enter__.return_value.cursor.return_value.__enter__.return_value
        # The implementation uses conn.cursor under conn.transaction; mocks
        # must follow that shape instead of a nested transaction proxy.
        cur = connection.cursor.return_value.__enter__.return_value
        cur.fetchone.side_effect = [(0,)] * len(audit.CHECKS)
        result = audit.check_operational_consistency(FAKE_URL)
        self.assertEqual(result["status"], "ok")
        self.assertEqual(len(result["checks"]), len(audit.CHECKS))
        self.assertTrue(all(x["count"] == 0 for x in result["checks"]))
        statements = [c.args[0] for c in cur.execute.call_args_list]
        self.assertEqual(
            statements[0], "SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY"
        )
        self.assertEqual(len(statements), 3 + len(audit.CHECKS))
        self.assertTrue(all(
            s == query for s, query in zip(
                statements[3:], [check[-1] for check in audit.CHECKS]
            )
        ))
        connection.transaction.assert_called_once()

    @patch.object(audit, "validate_staging_structure", return_value=("ok", []))
    @patch("psycopg.connect")
    def test_flags_specific_aggregate_counts_without_company_details(
        self, connect, schema,
    ):
        connection = connect.return_value.__enter__.return_value
        cursor = connection.cursor.return_value.__enter__.return_value
        cursor.fetchone.side_effect = [
            (2,) if i in (1, 4, 8) else (0,)
            for i in range(len(audit.CHECKS))
        ]
        result = audit.check_operational_consistency(FAKE_URL)
        self.assertEqual(result["status"], "issues_found")
        self.assertEqual(sum(x["count"] for x in result["checks"]), 6)
        self.assertNotIn("do-not-display-secret", str(result))
        self.assertTrue(all(set(x) == {
            "id", "area", "label", "severity", "count",
        } for x in result["checks"]))

    @patch.object(audit, "validate_staging_structure", return_value=("ok", []))
    @patch("psycopg.connect", side_effect=RuntimeError(
        "postgresql://operator:do-not-display-secret@localhost/db"
    ))
    def test_connection_exception_fails_closed_and_redacts_secrets(self, *_):
        result = audit.check_operational_consistency(FAKE_URL)
        self.assertEqual(result, {"status": "failed", "checks": []})
        self.assertNotIn("secret", str(result))


if __name__ == "__main__":
    unittest.main()
