"""Mobile PostgreSQL System and backup shortcut regression tests.

No live database, file write, or company data is needed for these tests.
"""
import unittest
from unittest.mock import patch

import postgres_system as system

URL = "postgresql://fictional-not-a-real-server"


class MobileSystemTests(unittest.TestCase):
    @patch.object(system, "st")
    @patch.object(system, "current_role", return_value="VIEWER")
    def test_backup_shortcut_hidden_from_non_admin(self, _role, st):
        system.render_postgres_quick_backup(URL)
        st.expander.assert_not_called()
        st.button.assert_not_called()

    @patch.object(system, "st")
    @patch.object(system, "current_role", return_value="ADMIN")
    def test_admin_mobile_backup_shortcut_does_not_read_without_click(
        self, _role, st,
    ):
        st.button.return_value = False
        with patch(
            "scripts.postgres_backup.export_postgres_backup"
        ) as export:
            system.render_postgres_quick_backup(URL)
        st.expander.assert_called_once()
        self.assertIn("hızlı erişim", st.expander.call_args.args[0])
        st.button.assert_called_once()
        export.assert_not_called()
        st.download_button.assert_not_called()

    @patch.object(system, "st")
    @patch.object(system, "current_role", return_value="ADMIN")
    @patch.object(system, "current_user", return_value={"username": "ci-admin"})
    def test_system_uses_simple_mobile_selector_not_nested_tabs(
        self, _user, _role, st,
    ):
        st.selectbox.return_value = "💾 Yedekleme"
        st.button.return_value = False
        system.render_postgres_system(URL)
        st.selectbox.assert_called_once()
        self.assertEqual(st.selectbox.call_args.args[0], "Sistem bölümü")
        self.assertIn("💾 Yedekleme", st.selectbox.call_args.args[1])
        st.tabs.assert_not_called()
        st.download_button.assert_not_called()

    @patch.object(system, "st")
    @patch.object(system, "current_role", return_value="VIEWER")
    def test_system_administration_denies_non_admin(self, _role, st):
        system.render_postgres_system(URL)
        st.error.assert_called_once()
        st.selectbox.assert_not_called()

    @patch.object(system, "st")
    @patch.object(system, "current_role", return_value="ADMIN")
    @patch.object(system, "current_user", return_value={"username": "ci-admin"})
    @patch(
        "scripts.postgres_backup.export_postgres_backup",
        return_value=("ok", b"CI fictional ZIP"),
    )
    def test_download_offered_only_after_explicit_user_click(
        self, export, _user, _role, st,
    ):
        st.selectbox.return_value = "💾 Yedekleme"
        st.button.return_value = True
        system.render_postgres_system(URL)
        export.assert_called_once_with(URL)
        st.download_button.assert_called_once()
        self.assertEqual(
            st.download_button.call_args.kwargs["data"], b"CI fictional ZIP"
        )
        self.assertTrue(
            st.download_button.call_args.kwargs["file_name"].endswith(".zip")
        )
        st.error.assert_not_called()

    @patch.object(system, "st")
    @patch.object(system, "current_role", return_value="ADMIN")
    @patch.object(system, "current_user", return_value={"username": "ci-admin"})
    @patch(
        "scripts.postgres_backup.export_postgres_backup",
        return_value=("failed", None),
    )
    def test_backup_errors_are_sanitized_and_do_not_offer_download(
        self, export, _user, _role, st,
    ):
        st.selectbox.return_value = "💾 Yedekleme"
        st.button.return_value = True
        system.render_postgres_system(URL)
        export.assert_called_once()
        st.error.assert_called_once()
        st.download_button.assert_not_called()


    @patch.object(system, "st")
    @patch.object(system, "current_role", return_value="ADMIN")
    @patch.object(system, "current_user", return_value={"username": "ci-admin"})
    @patch(
        "scripts.postgres_reconciliation.check_operational_consistency",
        return_value={
            "status": "issues_found",
            "checks": [{
                "id": "invalid_stock_quantities",
                "area": "Stok / Kalite",
                "label": "Negatif veya müsait miktarı aşan stok blokajı",
                "severity": "critical",
                "count": 2,
            }],
        },
    )
    def test_reconciliation_is_admin_only_and_read_only(
        self, check, _user, _role, st,
    ):
        st.selectbox.return_value = "🔍 Operasyon Mutabakatı"
        st.button.return_value = True
        system.render_postgres_system(URL)
        check.assert_called_once_with(URL)
        st.error.assert_called_once()
        st.dataframe.assert_called_once()
        st.download_button.assert_not_called()

    @patch.object(system, "st")
    @patch.object(system, "current_role", return_value="ADMIN")
    @patch.object(system, "current_user", return_value={"username": "ci-admin"})
    @patch(
        "scripts.postgres_reconciliation.check_operational_consistency",
    )
    def test_reconciliation_waits_for_explicit_click(
        self, check, _user, _role, st,
    ):
        st.selectbox.return_value = "🔍 Operasyon Mutabakatı"
        st.button.return_value = False
        system.render_postgres_system(URL)
        check.assert_not_called()
        st.dataframe.assert_not_called()

    @patch.object(system, "st")
    @patch.object(system, "current_role", return_value="ADMIN")
    @patch.object(system, "current_user", return_value={"username": "ci-admin"})
    @patch(
        "scripts.postgres_reconciliation.check_operational_consistency",
        return_value={"status": "ok", "checks": []},
    )
    def test_reconciliation_reports_no_issues_without_changes(
        self, check, _user, _role, st,
    ):
        st.selectbox.return_value = "🔍 Operasyon Mutabakatı"
        st.button.return_value = True
        system.render_postgres_system(URL)
        check.assert_called_once_with(URL)
        # The page shows its existing PostgreSQL-connected success banner
        # as well as the separate ten-check reconciliation result.
        self.assertTrue(any(
            "10 kontrolde tutarsızlık bulunmadı" in str(call.args[0])
            for call in st.success.call_args_list
        ))
        st.error.assert_not_called()


if __name__ == "__main__":
    unittest.main()
