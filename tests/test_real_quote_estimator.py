"""Real-input quote calculation: deterministic currency and working capital.

Fictional numeric test inputs only. No company/customer database connection.
"""
from decimal import Decimal
import math
import unittest

from scripts.real_quote_estimator import (
    QuoteInputError, calculate_real_quote,
)


def preview(**overrides):
    values = {
        "company_code": "AS_ILERI_GIDA",
        "quantity_kg": "1000",
        "buy_price_per_kg": "2",
        "buy_currency": "EUR",
        "buy_fx_to_base": "1",
        "base_currency": "EUR",
        "sell_price_per_kg": "3",
        "sell_currency": "EUR",
        "sell_fx_to_base": "1",
        "freight_total_base": "100",
        "customs_total_base": "50",
        "import_other_total_base": "0",
        "handling_total_base": "0",
        "annual_finance_rate_pct": "0",
        "prepayment_pct": "0",
        "prepayment_lead_days": 0,
        "supplier_balance_due_days": 0,
        "stock_days": 0,
        "customer_credit_days": 0,
        "sales_commission_pct": "0",
        "target_margin_pct": "10",
    }
    values.update(overrides)
    return calculate_real_quote(**values)


class RealQuoteEstimatorTests(unittest.TestCase):
    def test_real_cost_and_target_price_with_exact_decimals(self):
        x = preview()
        self.assertEqual(x["goods_base"], Decimal("2000"))
        self.assertEqual(x["logistics_base"], Decimal("150"))
        self.assertEqual(x["cost_per_kg_base"], Decimal("2.15"))
        self.assertEqual(x["profit_base"], Decimal("850"))
        self.assertEqual(
            x["margin_pct"], Decimal("850") / Decimal("3000") * 100,
        )
        self.assertTrue(x["meets_target"])
        self.assertEqual(x["break_even_sell_price"], Decimal("2.15"))
        self.assertAlmostEqual(float(x["required_sell_price"]), 2.38888888, places=6)

    def test_payment_split_changes_financing_exposure(self):
        x = preview(
            freight_total_base="100", customs_total_base="0",
            annual_finance_rate_pct="36.5",
            prepayment_pct="20", prepayment_lead_days=30,
            supplier_balance_due_days=60, stock_days=30,
            customer_credit_days=60,
        )
        self.assertEqual(x["weighted_goods_finance_days"], Decimal("48.0"))
        self.assertEqual(x["goods_finance_base"], Decimal("96.00000"))
        self.assertEqual(x["logistics_finance_base"], Decimal("9.000"))
        self.assertEqual(x["finance_total_base"], Decimal("105.00000"))
        self.assertEqual(x["total_cost_base"], Decimal("2205.00000"))
        self.assertEqual(x["profit_base"], Decimal("795.00000"))

    def test_supplier_payment_after_collection_does_not_finance_goods(self):
        x = preview(
            customs_total_base=0, annual_finance_rate_pct=36.5,
            prepayment_pct=0, supplier_balance_due_days=150,
            stock_days=30, customer_credit_days=60,
        )
        self.assertEqual(x["weighted_goods_finance_days"], Decimal(0))
        self.assertEqual(x["goods_finance_base"], Decimal(0))
        self.assertEqual(x["logistics_finance_base"], Decimal("9.000"))

    def test_different_buy_and_sell_currencies_require_manual_fx(self):
        x = preview(
            buy_currency="USD", buy_fx_to_base="0.9",
            sell_currency="GBP", sell_fx_to_base="1.15",
            target_margin_pct=20, sales_commission_pct=5,
        )
        self.assertEqual(x["goods_base"], Decimal("1800.0"))
        self.assertEqual(x["gross_sales_base"], Decimal("3450.00"))
        self.assertEqual(x["commission_base"], Decimal("172.5000"))
        self.assertEqual(x["net_sales_base"], Decimal("3277.5000"))
        self.assertAlmostEqual(
            float(x["required_sell_price"]),
            float(x["cost_per_kg_base"] / Decimal(".8") / Decimal(".95") / Decimal("1.15")),
            places=12,
        )
        self.assertTrue(x["meets_target"])

    def test_no_entered_selling_price_shows_required_price_but_not_profit(self):
        x = preview(sell_price_per_kg=0)
        self.assertIsNone(x["profit_base"])
        self.assertIsNone(x["margin_pct"])
        self.assertIsNone(x["meets_target"])
        self.assertGreater(x["required_sell_price"], Decimal(0))

    def test_no_demo_seed_and_all_four_company_codes_are_labels_only(self):
        for company_code in (
            "AS_ILERI_GIDA", "PLANET_INGREDIENTS",
            "AS_FOOD_GLOBAL", "AS_ILERI_HOLDING",
        ):
            x = preview(company_code=company_code)
            self.assertEqual(x["company_code"], company_code)
            self.assertEqual(x["total_cost_base"], Decimal("2150"))

    def test_invalid_inputs_fail_closed(self):
        cases = [
            {"company_code": "*"},
            {"company_code": "UNKNOWN"},
            {"quantity_kg": 0},
            {"quantity_kg": False},
            {"quantity_kg": -1},
            {"quantity_kg": math.nan},
            {"quantity_kg": math.inf},
            {"buy_price_per_kg": 0},
            {"buy_price_per_kg": "NaN"},
            {"buy_price_per_kg": "1e99999"},
            {"buy_currency": "AUD"},
            {"sell_currency": "USD", "sell_fx_to_base": 0},
            {"buy_currency": "GBP", "buy_fx_to_base": 0},
            {"buy_fx_to_base": 1.01},
            {"freight_total_base": -1},
            {"customs_total_base": -100},
            {"prepayment_pct": 100.1},
            {"annual_finance_rate_pct": 101},
            {"sales_commission_pct": 100},
            {"target_margin_pct": 100},
            {"prepayment_lead_days": -1},
            {"stock_days": 4.5},
            {"customer_credit_days": 3651},
        ]
        for case in cases:
            with self.subTest(case=case), self.assertRaises(QuoteInputError):
                preview(**case)

    def test_margin_measured_against_net_sales_not_gross_sales(self):
        x = preview(
            buy_price_per_kg=2, sell_price_per_kg=2.5,
            sales_commission_pct=10, target_margin_pct=10,
        )
        self.assertEqual(x["net_sales_base"], Decimal("2250.00"))
        self.assertEqual(x["profit_base"], Decimal("100.00"))
        self.assertFalse(x["meets_target"])


if __name__ == "__main__":
    unittest.main()
