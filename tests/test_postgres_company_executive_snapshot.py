"""Offline aggregate privacy/authorization tests, no database connection."""
import unittest
from unittest.mock import MagicMock, patch

from scripts import postgres_company_executive_snapshot as summary
from scripts.postgres_company_scope import CRITICAL_TABLES


class ExecutiveSnapshotTests(unittest.TestCase):
    def test_exact_eight_owned_modules_no_shared_crm_aggregation(self):
        self.assertEqual(tuple(summary.COUNTS), tuple(CRITICAL_TABLES))
        self.assertNotIn("customers", summary.COUNTS)
        self.assertNotIn("product_catalog", summary.COUNTS)
        self.assertEqual(
            {name for name, _, _, _ in summary.FINANCE_AGGREGATES},
            {"cash", "receivables_open", "payables_open"},
        )

    @patch.object(summary, "authorize_company_on_cursor", return_value=(
        "forbidden", None,
    ))
    def test_denied_principal_never_runs_aggregate_sql(self, authorize):
        cur = MagicMock()
        self.assertEqual(
            summary.company_executive_snapshot_on_cursor(
                cur, "ci-untrusted", "AS_FOOD_GLOBAL"
            ), ("forbidden", {}),
        )
        authorize.assert_called_once_with(
            cur, "ci-untrusted", "AS_FOOD_GLOBAL"
        )
        cur.execute.assert_not_called()

    @patch.object(summary, "authorize_company_on_cursor", return_value=(
        "not_ready", None,
    ))
    def test_missing_owner_columns_return_no_metrics(self, authorize):
        cur = MagicMock()
        self.assertEqual(
            summary.company_executive_snapshot_on_cursor(
                cur, "ci-user", "AS_ILERI_GIDA"
            ), ("not_ready", {}),
        )
        cur.execute.assert_not_called()

    def test_invalid_company_never_connects(self):
        with patch("psycopg.connect") as connect:
            self.assertEqual(
                summary.read_company_executive_snapshot(
                    "postgresql://user@host/db", "ci-user", "NOT_A_COMPANY",
                ), ("forbidden", {}),
            )
            connect.assert_not_called()

    @patch.object(summary, "authorize_company_on_cursor", return_value=(
        "ok", 42,
    ))
    def test_aggregate_queries_are_fixed_tenant_and_grant_bound(self, authorize):
        cur = MagicMock()
        cur.fetchone.return_value = (1,)
        cur.fetchall.return_value = [("EUR", 50), ("GBP", 120)]
        status, report = summary.company_executive_snapshot_on_cursor(
            cur, "ci-user", "AS_FOOD_GLOBAL"
        )
        self.assertEqual(status, "ok")
        self.assertEqual(report["company_code"], "AS_FOOD_GLOBAL")
        self.assertFalse(report["cross_company_totals"])
        self.assertFalse(report["consolidation_verified"])
        self.assertEqual(report["counts"]["purchase_orders"], 1)
        self.assertEqual(
            report["finance_by_currency"]["cash"],
            ({"currency": "EUR", "amount": 50},
             {"currency": "GBP", "amount": 120}),
        )
        self.assertEqual(cur.execute.call_count, 12)  # 8 counts, 3 FX, inventory
        for call in cur.execute.call_args_list:
            sql, params = call.args
            self.assertIn('b.legal_entity_id=%s', sql)
            self.assertIn('"ct_app"."company_read_grants"', sql)
            self.assertIn('g.principal_id=%s AND g.can_read=TRUE', sql)
            self.assertEqual(params, (42, "AS_FOOD_GLOBAL", "ci-user"))
            self.assertNotIn("AS_FOOD_GLOBAL", sql)
            self.assertNotIn("ci-user", sql)
        self.assertIn(
            'GROUP BY b.currency',
            cur.execute.call_args_list[-2].args[0]
            if False else cur.execute.call_args_list[8].args[0],
        )

    @patch.object(summary, "authorize_company_on_cursor", return_value=(
        "ok", 42,
    ))
    def test_currencies_not_converted_or_combined(self, authorize):
        cur = MagicMock()
        cur.fetchone.return_value = (0, 0)
        cur.fetchall.return_value = [("EUR", 100), ("TRY", 200)]
        status, report = summary.company_executive_snapshot_on_cursor(
            cur, "ci-user", "AS_ILERI_GIDA"
        )
        self.assertEqual(status, "ok")
        self.assertEqual(
            {x["currency"] for x in report["finance_by_currency"]["cash"]},
            {"EUR", "TRY"},
        )
        self.assertNotIn("converted", report)
        self.assertNotIn("consolidated_total", report)


if __name__ == "__main__":
    unittest.main()
