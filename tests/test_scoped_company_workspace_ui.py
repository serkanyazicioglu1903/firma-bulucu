"""Security tests: preview mode suppresses legacy tabs, pages and DB reads."""
import os
import unittest
from unittest.mock import patch

import scoped_company_workspace_ui as ui


class CompanyScopedViewerTests(unittest.TestCase):
    @patch.object(ui, "st")
    def test_opt_in_disabled_by_default(self, st):
        st.secrets.get.return_value = ""
        with patch.dict(os.environ, {}, clear=True):
            self.assertFalse(ui.scoped_company_view_enabled())
        st.secrets.get.return_value = "1"
        self.assertFalse(ui.scoped_company_view_enabled())
        st.secrets.get.return_value = ui.REVIEW_MODE
        self.assertTrue(ui.scoped_company_view_enabled())

    @patch.object(ui, "read_company_records")
    @patch.object(ui, "verified_company_principal", return_value=None)
    @patch.object(ui, "st")
    def test_unsigned_user_never_gets_selectors_or_queries(self, st, _user, read):
        ui.render_scoped_company_workspace("not-a-live-db")
        st.error.assert_called_once()
        st.selectbox.assert_not_called()
        st.button.assert_not_called()
        read.assert_not_called()

    @patch.object(ui, "read_company_records")
    @patch.object(ui, "verified_company_principal", return_value="ci-user")
    @patch.object(ui, "st")
    def test_selection_does_not_issue_read_before_click(self, st, user, read):
        st.button.return_value = False
        ui.render_scoped_company_workspace("not-a-live-db")
        self.assertEqual(st.selectbox.call_count, 2)
        read.assert_not_called()
        st.dataframe.assert_not_called()

    @patch.object(ui, "read_company_records", return_value=("forbidden", []))
    @patch.object(ui, "verified_company_principal", return_value="ci-user")
    @patch.object(ui, "st")
    def test_other_company_is_denied_with_no_rows(self, st, user, read):
        st.button.return_value = True
        st.selectbox.side_effect = ["AS_FOOD_GLOBAL", "Banka / Kasa"]
        ui.render_scoped_company_workspace("db-review")
        read.assert_called_once_with(
            "db-review", "ci-user", "AS_FOOD_GLOBAL", "Banka / Kasa"
        )
        st.error.assert_called_once()
        st.dataframe.assert_not_called()

    @patch.object(ui, "read_company_records", return_value=("not_ready", []))
    @patch.object(ui, "verified_company_principal", return_value="ci-user")
    @patch.object(ui, "st")
    def test_missing_company_migration_is_not_ready(self, st, user, read):
        st.button.return_value = True
        st.selectbox.side_effect = ["AS_ILERI_HOLDING", "Stok"]
        ui.render_scoped_company_workspace("db-review")
        st.dataframe.assert_not_called()
        st.warning.assert_called()
        st.success.assert_not_called()

    @patch.object(ui, "read_company_records", return_value=("ok", [
        {"id": 1, "name": "CI EXAMPLE BANK", "currency": "EUR"}
    ]))
    @patch.object(ui, "verified_company_principal", return_value="ci-user")
    @patch.object(ui, "st")
    def test_authorized_rows_only_from_granted_backend_adapter(self, st, user, read):
        st.button.return_value = True
        st.selectbox.side_effect = ["AS_ILERI_GIDA", "Banka / Kasa"]
        ui.render_scoped_company_workspace("db-review")
        read.assert_called_once_with(
            "db-review", "ci-user", "AS_ILERI_GIDA", "Banka / Kasa"
        )
        st.dataframe.assert_called_once()
        self.assertEqual(len(st.dataframe.call_args.args[0]), 1)
        st.metric.assert_not_called()
        st.download_button.assert_not_called()


if __name__ == "__main__":
    unittest.main()
