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


    @patch.object(system, "st")
    @patch.object(system, "current_role", return_value="VIEWER")
    def test_reconciliation_shortcut_hidden_for_non_admin(self, _role, st):
        system.render_postgres_quick_reconciliation(URL)
        st.expander.assert_not_called()

    @patch.object(system, "st")
    @patch.object(system, "current_role", return_value="ADMIN")
    @patch("scripts.postgres_reconciliation.check_operational_consistency")
    def test_reconciliation_shortcut_is_click_only(self, check, _role, st):
        st.button.return_value = False
        system.render_postgres_quick_reconciliation(URL)
        st.expander.assert_called_once()
        self.assertIn("hızlı erişim", st.expander.call_args.args[0])
        check.assert_not_called()

    @patch.object(system, "st")
    @patch.object(system, "current_role", return_value="ADMIN")
    @patch(
        "scripts.postgres_reconciliation.check_operational_consistency",
        return_value={"status": "ok", "checks": []},
    )
    def test_reconciliation_shortcut_uses_existing_read_only_check(
        self, check, _role, st,
    ):
        st.button.return_value = True
        system.render_postgres_quick_reconciliation(URL)
        check.assert_called_once_with(URL)
        self.assertTrue(any(
            "10 kontrolde tutarsızlık bulunmadı" in str(call.args[0])
            for call in st.success.call_args_list
        ))


    @patch.object(system, "st")
    @patch.object(system, "current_role", return_value="VIEWER")
    def test_bulk_import_never_available_to_non_admin(self, role, st):
        system.render_postgres_master_import(URL)
        st.expander.assert_not_called()
        st.file_uploader.assert_not_called()

    @patch.object(system, "st")
    @patch.object(system, "current_role", return_value="ADMIN")
    def test_bulk_import_initially_template_only_no_writes(self, role, st):
        st.selectbox.return_value = "Müşteriler"
        st.file_uploader.return_value = None
        with patch("scripts.postgres_master_import.import_new_masters") as create:
            system.render_postgres_master_import(URL)
        create.assert_not_called()
        st.download_button.assert_called_once()
        self.assertTrue(
            st.download_button.call_args.kwargs["data"].startswith(b"\xef\xbb\xbf")
        )
        st.button.assert_not_called()

    @patch.object(system, "st")
    @patch.object(system, "current_role", return_value="ADMIN")
    def test_bulk_import_preview_without_confirmation_is_read_only(
        self, role, st,
    ):
        from unittest.mock import MagicMock
        uploaded = MagicMock()
        from scripts.postgres_master_import import template_csv, parse_master_csv
        uploaded.getvalue.return_value = (
            template_csv("Müşteriler") + b"Onayli CI Musteri,Turkiye,,,,,,\r\n"
        )
        self.assertEqual(
            parse_master_csv(uploaded.getvalue(), "Müşteriler")[0],
            "ok", "The actual CSV template must be valid before UI submission.",
        )
        st.selectbox.return_value = "Müşteriler"
        st.file_uploader.return_value = uploaded
        st.checkbox.return_value = False
        st.text_input.return_value = ""
        st.button.return_value = False
        with patch("scripts.postgres_master_import.import_new_masters") as create:
            system.render_postgres_master_import(URL)
        self.assertTrue(st.dataframe.called, repr(st.error.call_args_list))
        self.assertEqual(st.button.call_args.kwargs["disabled"], True)
        create.assert_not_called()

    @patch.object(system, "st")
    @patch.object(system, "current_role", return_value="ADMIN")
    @patch.object(system, "current_user", return_value={"username": "ci-admin"})
    def test_bulk_import_confirmed_real_data_batch_is_explicitly_requested(
        self, user, role, st,
    ):
        from unittest.mock import MagicMock
        from scripts.postgres_master_import import APPROVAL
        uploaded = MagicMock()
        from scripts.postgres_master_import import template_csv, parse_master_csv
        uploaded.getvalue.return_value = (
            template_csv("Müşteriler") + b"Onayli CI Musteri,Turkiye,,,,,,\r\n"
        )
        self.assertEqual(
            parse_master_csv(uploaded.getvalue(), "Müşteriler")[0],
            "ok", "The actual CSV template must be valid before UI submission.",
        )
        st.selectbox.return_value = "Müşteriler"
        st.file_uploader.return_value = uploaded
        st.checkbox.return_value = True
        st.text_input.return_value = APPROVAL
        st.button.return_value = True
        with patch(
            "scripts.postgres_master_import.import_new_masters",
            return_value=("ok", 1),
        ) as create:
            system.render_postgres_master_import(URL)
        self.assertTrue(create.called, repr(st.error.call_args_list))
        kwargs = create.call_args.kwargs
        self.assertEqual(kwargs["role"], "ADMIN")
        self.assertEqual(kwargs["actor"], "ci-admin")
        self.assertEqual(kwargs["domain"], "Müşteriler")
        self.assertEqual(kwargs["confirmation"], APPROVAL)
        self.assertIs(kwargs["backup_confirmed"], True)
        st.success.assert_called()


    @patch.object(system, "st")
    @patch.object(system, "current_role", return_value="VIEWER")
    def test_security_shortcut_not_visible_to_non_admin(self, role, st):
        system.render_postgres_quick_security(URL)
        st.expander.assert_not_called()
        st.button.assert_not_called()

    @patch.object(system, "st")
    @patch.object(system, "current_role", return_value="ADMIN")
    def test_security_shortcut_never_queries_until_click(self, role, st):
        st.button.return_value = False
        with patch(
            "scripts.postgres_security_audit.audit_postgres_security"
        ) as checker:
            system.render_postgres_quick_security(URL)
        st.expander.assert_called_once()
        st.button.assert_called_once()
        checker.assert_not_called()

    @patch.object(system, "st")
    @patch.object(system, "current_role", return_value="ADMIN")
    def test_security_shortcut_displays_review_not_false_production_approval(
        self, role, st,
    ):
        st.button.return_value = True
        with patch(
            "scripts.postgres_security_audit.audit_postgres_security",
            return_value={
                "status": "review_required",
                "checks": [
                    {"label": "TLS", "status": "uygun",
                     "detail": "Bağlantı şifreli"},
                ],
                "external": ["Supabase otomatik yedekleme: bilinmiyor"],
            },
        ) as checker:
            system.render_postgres_quick_security(URL)
        checker.assert_called_once_with(URL)
        st.info.assert_called_once()
        st.dataframe.assert_called_once()
        st.success.assert_not_called()


    @patch.object(system, "st")
    @patch.object(system, "current_role", return_value="VIEWER")
    def test_backup_zip_verification_is_admin_only(self, _role, st):
        system.render_postgres_quick_backup_verify()
        st.expander.assert_not_called()
        st.file_uploader.assert_not_called()

    @patch.object(system, "st")
    @patch.object(system, "current_role", return_value="ADMIN")
    def test_zip_verification_waits_for_uploaded_file(self, _role, st):
        st.file_uploader.return_value = None
        with patch("scripts.postgres_backup_verify.inspect_export_zip") as verify:
            system.render_postgres_quick_backup_verify()
        st.file_uploader.assert_called_once()
        verify.assert_not_called()
        st.button.assert_not_called()

    @patch.object(system, "st")
    @patch.object(system, "current_role", return_value="ADMIN")
    def test_zip_verification_only_after_click(self, _role, st):
        from unittest.mock import MagicMock
        uploaded = MagicMock()
        uploaded.getvalue.return_value = b"FAKE-PRIVATE-ARCHIVE-IS-NEVER-EXPORTED"
        st.file_uploader.return_value = uploaded
        st.button.return_value = False
        with patch("scripts.postgres_backup_verify.inspect_export_zip") as verify:
            system.render_postgres_quick_backup_verify()
        verify.assert_not_called()
        uploaded.getvalue.assert_not_called()

    @patch.object(system, "st")
    @patch.object(system, "current_role", return_value="ADMIN")
    def test_zip_verification_reports_only_safe_aggregates(self, _role, st):
        from unittest.mock import MagicMock
        uploaded = MagicMock()
        uploaded.getvalue.return_value = b"FICTIONAL-ZIP"
        st.file_uploader.return_value = uploaded
        st.button.return_value = True
        st.text_input.return_value = ""
        summary = {
            "table_count": 26, "row_count": 1, "table_counts": {"customers": 1},
            "sha256": "b" * 64, "exported_utc": "2026-10-11T07:00:00Z",
            "restoration_tested": False,
        }
        with patch(
            "scripts.postgres_backup_verify.inspect_export_zip",
            return_value=("verified_format", summary),
        ) as verify:
            system.render_postgres_quick_backup_verify()
        verify.assert_called_once_with(b"FICTIONAL-ZIP")
        st.success.assert_called_once()
        self.assertIn("geri yükleme değildir", st.success.call_args.args[0])
        st.dataframe.assert_called_once()
        st.error.assert_not_called()


    @patch.object(system, "st")
    @patch.object(system, "current_role", return_value="ADMIN")
    def test_zip_rejects_mismatch_before_internal_checksum_is_checked(
        self, _role, st,
    ):
        from unittest.mock import MagicMock

        upload = MagicMock()
        upload.getvalue.return_value = b"synthetic-but-not-expected"
        st.file_uploader.return_value = upload
        st.text_input.return_value = "0" * 64
        st.button.return_value = True
        with patch("scripts.postgres_backup_verify.inspect_export_zip") as verify:
            system.render_postgres_quick_backup_verify()
        verify.assert_not_called()
        st.error.assert_called_once()
        st.success.assert_not_called()

    @patch.object(system, "st")
    @patch.object(system, "current_role", return_value="VIEWER")
    def test_encrypted_backup_hidden_from_non_admin(self, _role, st):
        system.render_postgres_quick_encrypted_backup(URL)
        st.expander.assert_not_called()
        st.text_input.assert_not_called()

    @patch.object(system, "st")
    @patch.object(system, "current_role", return_value="ADMIN")
    def test_encrypted_export_never_runs_without_confirmation(self, _role, st):
        st.text_input.side_effect = ["", "", "", ""]
        st.checkbox.return_value = False
        st.file_uploader.return_value = None
        st.button.return_value = False
        with patch("scripts.postgres_backup.export_postgres_backup") as export:
            system.render_postgres_quick_encrypted_backup(URL)
        export.assert_not_called()
        st.download_button.assert_not_called()
        self.assertTrue(st.button.call_args.kwargs["disabled"])

    @patch.object(system, "st")
    @patch.object(system, "current_role", return_value="ADMIN")
    def test_encrypted_backup_download_requires_explicit_click(
        self, _role, st,
    ):
        from scripts.postgres_encrypted_backup import MAGIC
        password = "Sample-safe-passphrase-2026!"
        st.text_input.side_effect = [password, password, "", ""]
        st.checkbox.return_value = True
        st.file_uploader.return_value = None
        st.button.return_value = True
        with patch(
            "scripts.postgres_backup.export_postgres_backup",
            return_value=("ok", b"fictional-zip"),
        ) as export:
            with patch(
                "scripts.postgres_encrypted_backup.encrypt_export_zip",
                return_value=("encrypted", MAGIC + b"CI-only-ciphertext"),
            ) as encrypt:
                system.render_postgres_quick_encrypted_backup(URL)
        export.assert_called_once_with(URL)
        encrypt.assert_called_once_with(b"fictional-zip", password)
        st.download_button.assert_called_once()
        self.assertTrue(
            st.download_button.call_args.kwargs["file_name"].endswith(".asct")
        )

    @patch.object(system, "st")
    @patch.object(system, "current_role", return_value="ADMIN")
    @patch.object(system, "st")
    @patch.object(system, "current_role", return_value="ADMIN")
    def test_encrypted_wrong_saved_hash_refuses_decryption(self, _role, st):
        from unittest.mock import MagicMock

        upload = MagicMock()
        upload.getvalue.return_value = b"synthetic encrypted file bytes"
        st.text_input.side_effect = ["", "", "fictional-password", "0" * 64]
        st.checkbox.return_value = False
        st.file_uploader.return_value = upload
        st.button.side_effect = [False, True]
        with patch(
            "scripts.postgres_encrypted_backup.inspect_encrypted_export"
        ) as inspect:
            system.render_postgres_quick_encrypted_backup(URL)
        inspect.assert_not_called()
        st.error.assert_called_once()
        st.success.assert_not_called()

    def test_encrypted_file_verification_without_live_database(self, _role, st):
        from unittest.mock import MagicMock
        upload = MagicMock()
        upload.getvalue.return_value = b"CI only encrypted file"
        st.text_input.side_effect = ["", "", "Safe-verify-password-2026!", ""]
        st.checkbox.return_value = False
        st.file_uploader.return_value = upload
        st.button.side_effect = [False, True]
        summary = {
            "table_count": 26, "row_count": 2,
            "encrypted_sha256": "e" * 64,
        }
        with patch("scripts.postgres_backup.export_postgres_backup") as export:
            with patch(
                "scripts.postgres_encrypted_backup.inspect_encrypted_export",
                return_value=("verified_encrypted", summary),
            ) as inspect:
                system.render_postgres_quick_encrypted_backup(URL)
        export.assert_not_called()
        inspect.assert_called_once_with(
            b"CI only encrypted file", "Safe-verify-password-2026!"
        )
        st.success.assert_called_once()
        st.error.assert_not_called()


if __name__ == "__main__":
    unittest.main()
