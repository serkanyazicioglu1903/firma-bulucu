"""Review legal-entity separation without touching real company records."""
import unittest
from unittest.mock import patch

from scripts.postgres_company_scope import (
    CRITICAL_TABLES, assess_company_scope, summarize_entity_columns,
)


class CompanyScopeTests(unittest.TestCase):
    def test_missing_direct_entity_fields_is_a_release_review_gate(self):
        result = summarize_entity_columns([])
        self.assertEqual(result["status"], "review_required")
        self.assertEqual(result["checked_count"], 8)
        self.assertEqual(set(result["without_direct_entity"]), set(CRITICAL_TABLES))
        self.assertFalse(result["isolation_verified"])

    def test_even_all_entity_columns_do_not_certify_isolation(self):
        result = summarize_entity_columns([
            (table, "legal_entity_id") for table in CRITICAL_TABLES
        ])
        self.assertEqual(result["without_direct_entity"], ())
        self.assertEqual(len(result["with_direct_entity"]), 8)
        self.assertEqual(result["status"], "review_required")
        self.assertFalse(result["isolation_verified"])

    def test_partial_and_duplicate_metadata_is_safe(self):
        result = summarize_entity_columns([
            ("cash_accounts", "company_id"),
            ("cash_accounts", "legal_entity_id"),
        ])
        self.assertEqual(result["with_direct_entity"], ("cash_accounts",))
        self.assertEqual(len(result["without_direct_entity"]), 7)

    def test_unexpected_metadata_is_rejected(self):
        with self.assertRaises(ValueError):
            summarize_entity_columns([("financial_notes", "company_id")])

    @patch("scripts.postgres_company_scope.validate_test_url", return_value=False)
    def test_invalid_url_never_connects(self, _url):
        result = assess_company_scope("not-a-postgres-url")
        self.assertEqual(result["status"], "failed")
        self.assertFalse(result["isolation_verified"])


if __name__ == "__main__":
    unittest.main()
