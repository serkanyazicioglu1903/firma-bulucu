"""Optional company review mode is exclusive of unscoped Control Tower tabs."""
import unittest
from unittest.mock import patch

import control_tower as ct


class ScopedCompanyRoutingTests(unittest.TestCase):
    @patch.object(ct, "st")
    @patch.object(ct, "render_postgres_quick_backup")
    @patch.object(ct, "render_postgres_master_import")
    @patch.object(ct, "render_scoped_company_workspace")
    @patch.object(ct, "postgres_url", return_value="db-only-ci")
    @patch.object(ct, "scoped_company_view_enabled", return_value=True)
    @patch.object(ct, "login_gate", return_value=True)
    def test_enabled_live_mode_replaces_all_unscoped_business_tabs(
        self, login, enabled, url, scoped, importer, backup, st,
    ):
        ct._render_control_tower_interface(live_postgres=True)
        scoped.assert_called_once_with("db-only-ci")
        st.tabs.assert_not_called()
        importer.assert_not_called()
        backup.assert_not_called()

    @patch.object(ct, "st")
    @patch.object(ct, "render_scoped_company_workspace")
    @patch.object(ct, "scoped_company_view_enabled", return_value=True)
    @patch.object(ct, "login_gate", return_value=False)
    def test_login_gate_stops_scoped_screen(
        self, login, enabled, scoped, st,
    ):
        ct._render_control_tower_interface(live_postgres=True)
        scoped.assert_not_called()
        st.tabs.assert_not_called()


if __name__ == "__main__":
    unittest.main()
