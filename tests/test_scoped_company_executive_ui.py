"""Signed UI executive summary never bypasses company-bound backend."""
import unittest
from unittest.mock import patch

import scoped_company_workspace_ui as ui


class CompanyExecutiveUiTests(unittest.TestCase):
    @patch.object(ui, "read_company_executive_snapshot")
    @patch.object(ui, "verified_company_principal", return_value=None)
    @patch.object(ui, "st")
    def test_unsigned_company_summary_never_reaches_db(
        self, st, _identity, snapshot
    ):
        ui.render_scoped_company_workspace("not-a-real-db")
        snapshot.assert_not_called()
        st.selectbox.assert_not_called()

    @patch.object(ui, "read_company_executive_snapshot")
    @patch.object(ui, "verified_company_principal", return_value="ci-user")
    @patch.object(ui, "st")
    def test_summary_not_fetched_without_button(
        self, st, _identity, snapshot
    ):
        st.selectbox.side_effect = ["AS_FOOD_GLOBAL", "Yönetici Özeti"]
        st.button.return_value = False
        ui.render_scoped_company_workspace("ci-db")
        snapshot.assert_not_called()
        st.dataframe.assert_not_called()

    @patch.object(ui, "read_company_executive_snapshot", return_value=(
        "forbidden", {},
    ))
    @patch.object(ui, "verified_company_principal", return_value="ci-user")
    @patch.object(ui, "st")
    def test_unauthorized_company_renders_no_totals(
        self, st, _identity, snapshot
    ):
        st.selectbox.side_effect = ["AS_ILERI_HOLDING", "Yönetici Özeti"]
        st.button.return_value = True
        ui.render_scoped_company_workspace("ci-db")
        snapshot.assert_called_once_with(
            "ci-db", "ci-user", "AS_ILERI_HOLDING"
        )
        st.error.assert_called_once()
        st.dataframe.assert_not_called()
        st.columns.assert_not_called()

    @patch.object(ui, "read_company_executive_snapshot", return_value=(
        "ok", {
            "counts": {
                "purchase_orders": 2, "shipments": 1, "inventory_lots": 3,
                "quality_cases": 0, "inventory_quantity_kg": 900,
                "quality_hold_kg": 50,
            },
            "finance_by_currency": {
                "cash": (
                    {"currency": "EUR", "amount": 25},
                    {"currency": "GBP", "amount": 600},
                ),
                "receivables_open": (
                    {"currency": "GBP", "amount": 85},
                ),
                "payables_open": (),
            },
            "consolidation_verified": False,
            "cross_company_totals": False,
        },
    ))
    @patch.object(ui, "verified_company_principal", return_value="ci-user")
    @patch.object(ui, "st")
    def test_company_summary_keeps_currency_rows_separate(
        self, st, _identity, snapshot
    ):
        st.selectbox.side_effect = ["AS_FOOD_GLOBAL", "Yönetici Özeti"]
        st.button.return_value = True
        ui.render_scoped_company_workspace("ci-db")
        snapshot.assert_called_once_with(
            "ci-db", "ci-user", "AS_FOOD_GLOBAL"
        )
        st.dataframe.assert_called_once()
        df = st.dataframe.call_args.args[0]
        self.assertEqual(
            set(df["Para birimi"]), {"EUR", "GBP"}
        )
        self.assertEqual(
            len(df[df["Gösterge"] == "Banka / kasa bakiyesi"]), 2
        )
        st.download_button.assert_not_called()


if __name__ == "__main__":
    unittest.main()
