"""Unit checks for conservative live acceptance assessment (no DB calls)."""
import unittest
from unittest.mock import patch
from scripts.postgres_acceptance import evaluate_acceptance

URL = "postgresql://fictional-user@localhost/db"
BASE = {
    "customers": 1,
    "purchase_orders": 0,
    "shipments": 0,
    "inventory_lots": 0,
    "quality_cases": 0,
    "payables": 0,
    "receivables": 0,
    "finance_transactions": 0,
}


class LiveAcceptanceTests(unittest.TestCase):
    @patch("scripts.postgres_acceptance.check_operational_consistency")
    @patch("scripts.postgres_acceptance.read_operational_counts")
    def test_empty_stock_and_finance_are_not_marked_verified(self, counts, audit):
        counts.return_value = ("ok", BASE)
        audit.return_value = {"status": "ok", "checks": [
            {"severity": "critical", "count": 0}
        ]}
        report = evaluate_acceptance(URL)
        self.assertEqual(report["status"], "review_required")
        self.assertEqual(report["critical"], 0)
        self.assertEqual(len(report["areas"]), 5)
        self.assertIn(
            "sınanmadı",
            next(x for x in report["areas"] if x["area"] == "Finans")["status"],
        )
        self.assertEqual(len(report["external_gates"]), 3)

    @patch("scripts.postgres_acceptance.check_operational_consistency")
    @patch("scripts.postgres_acceptance.read_operational_counts")
    def test_critical_integrity_blocks_acceptance(self, counts, audit):
        counts.return_value = ("ok", BASE)
        audit.return_value = {"status": "issues_found", "checks": [
            {"severity": "critical", "count": 2},
            {"severity": "warning", "count": 1},
        ]}
        report = evaluate_acceptance(URL)
        self.assertEqual(report["status"], "critical_issues")
        self.assertEqual(report["critical"], 2)

    @patch("scripts.postgres_acceptance.check_operational_consistency")
    @patch("scripts.postgres_acceptance.read_operational_counts")
    def test_backend_failures_do_not_claim_approval(self, counts, audit):
        counts.return_value = ("failed", {})
        self.assertEqual(evaluate_acceptance(URL)["status"], "failed")
        audit.assert_not_called()
        counts.return_value = ("ok", BASE)
        audit.return_value = {"status": "failed", "checks": []}
        self.assertEqual(evaluate_acceptance(URL)["status"], "failed")


if __name__ == "__main__":
    unittest.main()
