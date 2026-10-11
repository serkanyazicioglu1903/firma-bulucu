"""Offline UI authorization checks for the phone-accessible group panel."""
import unittest
from unittest.mock import patch

import group_readiness_ui as ui

URL = "postgresql://ci-fake-supabase-host/db"


class GroupReadinessUiTests(unittest.TestCase):
    @patch.object(ui, "evaluate_group_readiness")
    @patch.object(ui, "current_role", return_value="SALES")
    @patch.object(ui, "st")
    def test_non_admin_never_sees_company_panel_or_queries(self, st, _role, assess):
        ui.render_group_readiness_quick(URL)
        st.expander.assert_not_called()
        st.dataframe.assert_not_called()
        assess.assert_not_called()

    @patch.object(ui, "evaluate_group_readiness")
    @patch.object(ui, "current_role", return_value="ADMIN")
    @patch.object(ui, "st")
    def test_admin_preview_has_no_database_read_or_company_switch(self, st, _role, assess):
        st.button.return_value = False
        ui.render_group_readiness_quick(URL)
        st.expander.assert_called_once()
        self.assertIn("Grup Şirketleri", st.expander.call_args.args[0])
        st.dataframe.assert_called_once()
        df = st.dataframe.call_args.args[0]
        self.assertEqual(len(df), 4)
        self.assertEqual(tuple(df.columns), ("Şirket", "Durum"))
        st.warning.assert_called()
        st.selectbox.assert_not_called()
        st.metric.assert_not_called()
        assess.assert_not_called()

    @patch.object(ui, "evaluate_group_readiness")
    @patch.object(ui, "current_role", return_value="ADMIN")
    @patch.object(ui, "st")
    def test_explicit_click_reads_schema_only_and_warns(self, st, _role, assess):
        st.button.return_value = True
        assess.return_value = {
            "status": "blocked", "checked_tables": 8,
            "missing_owner_tables": 8,
            "production_multi_company_approved": False,
        }
        ui.render_group_readiness_quick(URL)
        assess.assert_called_once_with(URL)
        self.assertTrue(any(
            "8 tanesinde" in str(call.args[0])
            for call in st.error.call_args_list
        ))
        st.metric.assert_not_called()
        st.selectbox.assert_not_called()

    @patch.object(ui, "evaluate_group_readiness")
    @patch.object(ui, "current_role", return_value="ADMIN")
    @patch.object(ui, "st")
    def test_schema_unavailable_does_not_report_success(self, st, _role, assess):
        st.button.return_value = True
        assess.return_value = {"status": "failed"}
        ui.render_group_readiness_quick(URL)
        st.error.assert_called_once()
        st.success.assert_not_called()

    @patch.object(ui, "evaluate_group_readiness")
    @patch.object(ui, "current_role", return_value="ADMIN")
    @patch.object(ui, "st")
    def test_missing_url_never_attempts_database_lookup(self, st, _role, assess):
        st.button.return_value = True
        ui.render_group_readiness_quick("")
        assess.assert_not_called()
        st.error.assert_called_once()


if __name__ == "__main__":
    unittest.main()
