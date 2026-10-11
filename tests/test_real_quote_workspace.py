"""Quote screen privacy and spreadsheet export checks; no live database."""
from unittest.mock import patch
import unittest

import real_quote_workspace as ui
from scripts.real_quote_estimator import calculate_real_quote


def amount():
    return calculate_real_quote(
        company_code="AS_FOOD_GLOBAL", quantity_kg=1000,
        buy_price_per_kg=2, buy_currency="EUR", buy_fx_to_base=1,
        base_currency="EUR", sell_price_per_kg=3, sell_currency="EUR",
        sell_fx_to_base=1, freight_total_base=100,
        customs_total_base=0, import_other_total_base=0,
        handling_total_base=0, annual_finance_rate_pct=0,
        prepayment_pct=0, prepayment_lead_days=0,
        supplier_balance_due_days=0, stock_days=0,
        customer_credit_days=0, sales_commission_pct=0,
        target_margin_pct=10,
    )


class RealQuoteWorkspaceTests(unittest.TestCase):
    @patch.object(ui, "st")
    @patch.object(ui, "current_role", return_value="VIEWER")
    def test_noncommercial_role_sees_no_quote_inputs(self, role, st):
        ui.render_real_quote_workspace()
        st.form.assert_not_called()
        st.selectbox.assert_not_called()
        st.download_button.assert_not_called()
        st.warning.assert_called_once()

    @patch.object(ui, "st")
    def test_user_switch_discards_previous_customer_prices_and_result(self, st):
        st.session_state = {
            "ct_session_id": "new-session",
            ui._OWNER_KEY: ("person_a", "old-session"),
            "ct_rq_customer": "PRIVATE CUSTOMER",
            "ct_rq_product": "PRIVATE PRODUCT",
            "ct_rq_buy": 123.4,
            "ct_rq_base_ccy": "USD",
            "ct_rq_company": "PLANET_INGREDIENTS",
            ui._RESULT_KEY: {"profit_base": 123},
        }
        with patch.object(ui, "current_user", return_value={
            "username": "person_b", "role": "FINANCE",
        }):
            self.assertTrue(ui._bound_session())
        self.assertEqual(st.session_state[ui._OWNER_KEY], ("person_b", "new-session"))
        for key in (
            "ct_rq_customer", "ct_rq_product", "ct_rq_buy", "ct_rq_base_ccy",
            "ct_rq_company", ui._RESULT_KEY,
        ):
            self.assertNotIn(key, st.session_state)

    @patch.object(ui, "st")
    def test_missing_session_does_not_expose_previous_quote(self, st):
        st.session_state = {
            ui._RESULT_KEY: {"private": "value"},
            "ct_rq_customer": "PRIVATE",
        }
        with patch.object(ui, "current_user", return_value={"username": "person_a"}):
            self.assertFalse(ui._bound_session())
        self.assertNotIn(ui._RESULT_KEY, st.session_state)
        self.assertNotIn("ct_rq_customer", st.session_state)

    @patch.object(ui, "st")
    def test_changing_exchange_rate_context_clears_previous_fx_and_profit(self, st):
        st.session_state = {
            "ct_rq_buy_fx": 0.97,
            "ct_rq_sell_fx": 1.13,
            ui._RESULT_KEY: {"profit_base": 100},
            "ct_rq_qty": 24000,
        }
        ui._reset_result()
        for key in ("ct_rq_buy_fx", "ct_rq_sell_fx", ui._RESULT_KEY):
            self.assertNotIn(key, st.session_state)
        self.assertEqual(st.session_state["ct_rq_qty"], 24000)

    def test_csv_numeric_values_only_no_external_customer_strings(self):
        data = ui.quote_summary_csv(amount()).decode("utf-8-sig")
        self.assertIn("Gerçek toplam maliyet,2100", data)
        self.assertIn("AS_FOOD_GLOBAL", data)
        self.assertIn("Başabaş satış fiyatı / kg", data)
        self.assertNotIn("PRIVATE CUSTOMER", data)
        self.assertNotIn("=SUM(", data)
        self.assertIn("veritabanına kaydedilmedi", data)

    def test_root_app_wires_authenticated_company_review_safe_quote_tab(self):
        from pathlib import Path
        app_text = (Path(__file__).resolve().parents[1] / "app.py").read_text()
        self.assertIn("main_tab4", app_text)
        self.assertIn("render_real_quote_workspace()", app_text)
        self.assertLess(
            app_text.index('if review_mode != "disabled":'),
            app_text.index("main_tab1, main_tab2, main_tab3, main_tab4"),
        )


if __name__ == "__main__":
    unittest.main()
