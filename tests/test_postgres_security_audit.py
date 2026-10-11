"""Offline security audit tests: no secrets, row reads or mutations."""
import unittest
from unittest.mock import patch

from scripts import postgres_security_audit as audit

TEST_URL = "postgresql://fictional:never-print-password@127.0.0.1/example"


class PostgresSecurityAuditTests(unittest.TestCase):
    @patch.object(audit, "validate_staging_structure")
    def test_invalid_url_is_rejected_before_db(self, schema):
        result = audit.audit_postgres_security("sqlite:///local.db")
        self.assertEqual(result["status"], "invalid_url")
        schema.assert_not_called()

    @patch.object(audit, "validate_staging_structure", return_value=("bad", []))
    @patch("psycopg.connect")
    def test_wrong_schema_blocks_all_reads(self, connect, schema):
        result = audit.audit_postgres_security(TEST_URL)
        self.assertEqual(result["status"], "schema_mismatch")
        connect.assert_not_called()

    @patch.object(audit, "validate_staging_structure", return_value=("ok", []))
    @patch("psycopg.connect")
    def test_fixed_read_only_queries_reveal_no_account_names(
        self, connect, schema,
    ):
        db = connect.return_value.__enter__.return_value
        cursor = db.cursor.return_value.__enter__.return_value
        cursor.fetchone.side_effect = [
            (True,), (False, False, False), (26, 26), (True, True), (0, 0),
        ]
        result = audit.audit_postgres_security(TEST_URL)
        self.assertEqual(result["status"], "review_required")
        self.assertEqual(len(result["checks"]), 5)
        self.assertTrue(all(c["status"] == "uygun" for c in result["checks"]))
        self.assertEqual(len(result["external"]), 4)
        rendered = str(result)
        self.assertNotIn("never-print-password", rendered)
        sql = [call.args[0] for call in cursor.execute.call_args_list]
        self.assertEqual(sql[0], "SET TRANSACTION READ ONLY")
        self.assertEqual(len(sql), 8)
        self.assertFalse(any(
            statement.lstrip().upper().startswith(
                ("INSERT", "UPDATE", "DELETE", "DROP", "ALTER", "CREATE")
            ) for statement in sql
        ))
        db.transaction.assert_called_once()

    @patch.object(audit, "validate_staging_structure", return_value=("ok", []))
    @patch("psycopg.connect")
    def test_elevated_role_and_missing_rls_require_review(self, connect, schema):
        db = connect.return_value.__enter__.return_value
        cursor = db.cursor.return_value.__enter__.return_value
        cursor.fetchone.side_effect = [
            (True,), (True, True, True), (26, 0), (True, False), (2, 3),
        ]
        result = audit.audit_postgres_security(TEST_URL)
        self.assertEqual(result["status"], "review_required")
        self.assertTrue(any(c["status"] == "incele" for c in result["checks"]))
        self.assertTrue(any(c["status"] == "uyarı" for c in result["checks"]))
        self.assertTrue(any("Supabase" in x for x in result["external"]))

    @patch.object(audit, "validate_staging_structure", return_value=("ok", []))
    @patch("psycopg.connect")
    def test_rls_off_but_no_api_grants_does_not_claim_public_exposure(
        self, connect, schema,
    ):
        db = connect.return_value.__enter__.return_value
        cursor = db.cursor.return_value.__enter__.return_value
        cursor.fetchone.side_effect = [
            (True,), (False, False, False), (26, 0), (True, True), (0, 0),
        ]
        result = audit.audit_postgres_security(TEST_URL)
        self.assertEqual(result["status"], "review_required")
        api = next(x for x in result["checks"] if "API rolleri" in x["label"])
        rls = next(x for x in result["checks"] if "RLS" in x["label"])
        self.assertEqual(api["status"], "uygun")
        self.assertEqual(rls["status"], "incele")
        self.assertIn("doğrudan erişim izni bulunmadı", api["detail"])

    @patch.object(audit, "validate_staging_structure", return_value=("ok", []))
    @patch("psycopg.connect", side_effect=RuntimeError(
        "credential never-print-password in driver exception"
    ))
    def test_database_errors_are_sanitized(self, *_):
        result = audit.audit_postgres_security(TEST_URL)
        self.assertEqual(result["status"], "failed")
        self.assertNotIn("never-print-password", str(result))


if __name__ == "__main__":
    unittest.main()
