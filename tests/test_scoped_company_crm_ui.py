"""Signed CRM review UI never reads unverified or wrong-company rows."""
import unittest
from unittest.mock import patch

import scoped_company_workspace_ui as ui


class CompanyScopedCrmUiTests(unittest.TestCase):
    @patch.object(ui, "read_company_crm")
    @patch.object(ui, "verified_company_principal", return_value=None)
    @patch.object(ui, "st")
    def test_unsigned_user_never_triggers_crm_query(self, st, _identity, crm):
        ui.render_scoped_company_workspace("ci-db")
        crm.assert_not_called()
        st.selectbox.assert_not_called()

    @patch.object(ui, "read_company_crm")
    @patch.object(ui, "verified_company_principal", return_value="ci-user")
    @patch.object(ui, "st")
    def test_company_selector_not_a_grant_and_read_requires_button(
        self, st, _identity, crm,
    ):
        st.button.return_value = False
        st.selectbox.side_effect = ["AS_ILERI_HOLDING", "Müşteriler"]
        ui.render_scoped_company_workspace("ci-db")
        crm.assert_not_called()
        st.dataframe.assert_not_called()

    @patch.object(ui, "read_company_crm", return_value=("forbidden", []))
    @patch.object(ui, "verified_company_principal", return_value="ci-user")
    @patch.object(ui, "st")
    def test_denied_company_does_not_display_customers(
        self, st, _identity, crm,
    ):
        st.button.return_value = True
        st.selectbox.side_effect = ["AS_FOOD_GLOBAL", "Müşteriler"]
        ui.render_scoped_company_workspace("ci-db")
        crm.assert_called_once_with(
            "ci-db", "ci-user", "AS_FOOD_GLOBAL", "Müşteriler"
        )
        st.error.assert_called_once()
        st.dataframe.assert_not_called()

    @patch.object(ui, "read_company_crm", return_value=("not_ready", []))
    @patch.object(ui, "verified_company_principal", return_value="ci-user")
    @patch.object(ui, "st")
    def test_missing_database_ownership_keeps_crm_hidden(
        self, st, _identity, crm,
    ):
        st.button.return_value = True
        st.selectbox.side_effect = ["AS_ILERI_GIDA", "İrtibat Kişileri"]
        ui.render_scoped_company_workspace("ci-db")
        st.warning.assert_called()
        st.dataframe.assert_not_called()

    @patch.object(ui, "read_company_crm", return_value=(
        "ok", [{"id": 3, "name": "Fictional Customer"}]
    ))
    @patch.object(ui, "verified_company_principal", return_value="ci-user")
    @patch.object(ui, "st")
    def test_authorized_records_display_through_scoped_backend_only(
        self, st, _identity, crm,
    ):
        st.button.return_value = True
        st.selectbox.side_effect = ["PLANET_INGREDIENTS", "Müşteriler"]
        ui.render_scoped_company_workspace("ci-db")
        crm.assert_called_once_with(
            "ci-db", "ci-user", "PLANET_INGREDIENTS", "Müşteriler"
        )
        st.dataframe.assert_called_once()
        self.assertEqual(len(st.dataframe.call_args.args[0]), 1)
        st.download_button.assert_not_called()


if __name__ == "__main__":
    unittest.main()
