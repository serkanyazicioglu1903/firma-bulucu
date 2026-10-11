"""Group release state cannot become GO from a column count or empty DB."""
import unittest
from unittest.mock import patch

from scripts.postgres_group_readiness import (
    group_preview, summarize_group_structure, evaluate_group_readiness,
)
from scripts.postgres_company_scope import CRITICAL_TABLES


class FourCompanyReadinessTests(unittest.TestCase):
    def test_preview_has_four_company_labels_no_financial_data(self):
        report = group_preview()
        self.assertEqual(report["company_count"], 4)
        self.assertEqual(len(report["companies"]), 4)
        self.assertFalse(report["production_multi_company_approved"])
        for row in report["companies"]:
            self.assertEqual(set(row), {"code", "name", "status"})
            self.assertIn("doğrulanmadı", row["status"])

    def test_missing_owners_block_company_scope(self):
        report = summarize_group_structure({
            "status": "review_required",
            "without_direct_entity": tuple(CRITICAL_TABLES),
        })
        self.assertEqual(report["status"], "blocked")
        self.assertEqual(report["missing_owner_tables"], 8)
        self.assertFalse(report["production_multi_company_approved"])
        self.assertFalse(report["company_finance_verified"])
        self.assertFalse(report["consolidation_verified"])

    def test_columns_do_not_prove_multi_company_security(self):
        report = summarize_group_structure({
            "status": "review_required", "without_direct_entity": (),
        })
        self.assertEqual(report["status"], "review_required")
        self.assertEqual(report["missing_owner_tables"], 0)
        self.assertFalse(report["production_multi_company_approved"])
        self.assertFalse(report["company_finance_verified"])

    def test_error_and_malformed_metadata_fail_closed(self):
        for item in (None, {}, {"status": "failed"}, {
            "status": "review_required", "without_direct_entity": "purchase_orders"
        }, {"status": "review_required",
            "without_direct_entity": ("unknown_table",)}):
            with self.subTest(item=item):
                result = summarize_group_structure(item)
                self.assertEqual(result["status"], "failed")
                self.assertIsNone(result["missing_owner_tables"])
                self.assertFalse(result["production_multi_company_approved"])

    @patch("scripts.postgres_group_readiness.assess_company_scope")
    def test_database_audit_must_be_explicitly_called(self, assessor):
        assessor.return_value = {
            "status": "review_required", "without_direct_entity": (),
        }
        group_preview()
        assessor.assert_not_called()
        report = evaluate_group_readiness("CI DUMMY URL")
        assessor.assert_called_once_with("CI DUMMY URL")
        self.assertFalse(report["production_multi_company_approved"])


if __name__ == "__main__":
    unittest.main()
