"""Offline fail-closed test coverage for rollback-only PostgreSQL acceptance."""
import unittest
from unittest.mock import patch

from scripts import staging_acceptance as acceptance


class StagingAcceptanceTests(unittest.TestCase):
    def test_no_confirmation_never_connects(self):
        with patch.object(acceptance, "validate_staging_structure") as schema, \
             patch.object(acceptance, "run_transactional_staging_smoke") as smoke:
            result = acceptance.run_staging_acceptance(
                "postgresql://example:secret@localhost/db"
            )
            self.assertEqual(result["status"], "confirmation_required")
            schema.assert_not_called()
            smoke.assert_not_called()

    def test_invalid_url_stops_before_any_schema_check(self):
        with patch.object(acceptance, "validate_staging_structure") as schema:
            result = acceptance.run_staging_acceptance(
                "sqlite:///production.db", acceptance.ACKNOWLEDGEMENT
            )
            self.assertEqual(result["status"], "invalid_url")
            schema.assert_not_called()

    @patch.object(acceptance, "validate_test_url", return_value=True)
    @patch.object(acceptance, "validate_staging_structure", return_value=("mismatch", ["secret"]))
    @patch.object(acceptance, "run_transactional_staging_smoke")
    def test_schema_mismatch_blocks_all_writes(self, smoke, _schema, _url):
        result = acceptance.run_staging_acceptance(
            "not-displayed", acceptance.ACKNOWLEDGEMENT
        )
        self.assertEqual(result, {"status": "schema_failed", "completed": []})
        smoke.assert_not_called()

    @patch.object(acceptance, "validate_test_url", return_value=True)
    @patch.object(acceptance, "validate_staging_structure", return_value=("ok", []))
    @patch.object(acceptance, "run_transactional_staging_smoke", return_value=("failed", []))
    @patch.object(acceptance, "run_staging_business_pilot")
    def test_failed_rollback_crud_blocks_business(self, business, _smoke, _schema, _url):
        result = acceptance.run_staging_acceptance(
            "not-displayed", acceptance.ACKNOWLEDGEMENT
        )
        self.assertEqual(result, {"status": "transaction_failed", "completed": ["schema"]})
        business.assert_not_called()

    @patch.object(acceptance, "validate_test_url", return_value=True)
    @patch.object(acceptance, "validate_staging_structure", return_value=("ok", []))
    @patch.object(acceptance, "run_transactional_staging_smoke", return_value=("passed", []))
    @patch.object(acceptance, "run_staging_business_pilot", return_value=("failed", {}))
    def test_business_failure_is_not_reported_as_ready(self, *_):
        result = acceptance.run_staging_acceptance(
            "not-displayed", acceptance.ACKNOWLEDGEMENT
        )
        self.assertEqual(
            result, {"status": "business_failed", "completed": ["schema", "rollback_crud"]}
        )

    @patch.object(acceptance, "validate_test_url", return_value=True)
    @patch.object(acceptance, "validate_staging_structure", return_value=("ok", []))
    @patch.object(acceptance, "run_transactional_staging_smoke", return_value=("passed", ["customers"]))
    @patch.object(acceptance, "run_staging_business_pilot", return_value=("passed", {"secret": "data"}))
    def test_complete_success_has_no_business_data_or_credentials(self, *_):
        result = acceptance.run_staging_acceptance(
            "postgresql://user:private-password@localhost/db",
            acceptance.ACKNOWLEDGEMENT
        )
        self.assertEqual(
            result,
            {"status": "passed",
             "completed": ["schema", "rollback_crud", "rollback_business"]}
        )
        self.assertNotIn("private-password", str(result))
        self.assertNotIn("secret", str(result))

    @patch.object(acceptance, "validate_test_url", return_value=True)
    @patch.object(acceptance, "validate_staging_structure", side_effect=RuntimeError("postgresql://private"))
    def test_exception_is_sanitized(self, *_):
        result = acceptance.run_staging_acceptance(
            "postgresql://private", acceptance.ACKNOWLEDGEMENT
        )
        self.assertEqual(result, {"status": "failed", "completed": []})
        self.assertNotIn("private", str(result))


if __name__ == "__main__":
    unittest.main()
