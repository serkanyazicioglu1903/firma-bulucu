"""The signed four-company view must be exclusive across the ENTIRE app.

All tests use fictional credentials and mock URLs. No Supabase connections,
schema migrations, business writes, backup reads or feature-flag activation.
"""
import os
from pathlib import Path
import unittest
from unittest.mock import patch

from streamlit.testing.v1 import AppTest

import scoped_company_workspace_ui as scoped
import control_tower as ct


_APP = str(Path(__file__).resolve().parents[1] / "app.py")
_REVIEW = "REVIEW_ONLY_WITH_SIGNED_SESSION"


def signed_mode_app(mode, url):
    """Run app as synthetic session user without valid company HMAC."""
    # The test patches the server-only URL getter, not any real DB secrets.
    with patch.dict(os.environ, {"CT_COMPANY_SCOPED_VIEW_MODE": mode}), \
         patch("scripts.live_backend.postgres_url", return_value=url):
        app = AppTest.from_file(_APP, default_timeout=60)
        app.session_state["ct_user"] = {
            "username": "synthetic-admin", "display_name": "CI",
            "role": "ADMIN",
        }
        app.session_state["ct_session_id"] = "ci-only-unsigned"
        app.run()
        return app


class GlobalCompanyGateTests(unittest.TestCase):
    @patch.object(scoped, "st")
    def test_absent_flag_is_legacy_only(self, st):
        st.secrets.get.return_value = ""
        with patch.dict(os.environ, {"CT_COMPANY_SCOPED_VIEW_MODE": ""}):
            self.assertEqual(scoped.company_review_mode_state(), "disabled")
            self.assertFalse(scoped.scoped_company_view_enabled())

    @patch.object(scoped, "st")
    def test_exact_review_flag_only_and_both_same_values_allowed(self, st):
        st.secrets.get.return_value = ""
        with patch.dict(os.environ, {"CT_COMPANY_SCOPED_VIEW_MODE": _REVIEW}):
            self.assertEqual(scoped.company_review_mode_state(), "review")
            self.assertTrue(scoped.scoped_company_view_enabled())
        st.secrets.get.return_value = _REVIEW
        with patch.dict(os.environ, {"CT_COMPANY_SCOPED_VIEW_MODE": _REVIEW}):
            self.assertEqual(scoped.company_review_mode_state(), "review")

    @patch.object(scoped, "st")
    def test_typos_conflicts_or_wrong_types_fail_closed(self, st):
        for secret, env in [
            ("", "REVIEW_ONLY_WRONG"),
            (_REVIEW, "REVIEW_ONLY_WRONG"),
            ("REVIEW_ONLY_WRONG", ""),
            (True, _REVIEW),
        ]:
            st.secrets.get.return_value = secret
            with patch.dict(os.environ, {"CT_COMPANY_SCOPED_VIEW_MODE": env}):
                self.assertEqual(scoped.company_review_mode_state(), "invalid")
                self.assertFalse(scoped.scoped_company_view_enabled())

    def test_invalid_mode_blocks_entire_app_no_business_tabs(self):
        app = signed_mode_app("REVIEW_ONLY_WRONG", "")
        self.assertFalse(app.exception, str(app.exception))
        self.assertEqual(len(app.tabs), 0)
        self.assertTrue(any(
            "geçersiz" in item.message.lower() for item in app.error
        ))

    def test_review_mode_requires_postgres_before_any_tab(self):
        app = signed_mode_app(_REVIEW, "")
        self.assertFalse(app.exception, str(app.exception))
        self.assertEqual(len(app.tabs), 0)
        self.assertTrue(any("PostgreSQL" in item.message for item in app.error))

    def test_review_mode_denies_unsigned_user_without_showing_tabs(self):
        app = signed_mode_app(_REVIEW, "postgresql://ci.invalid/fictional")
        self.assertFalse(app.exception, str(app.exception))
        self.assertEqual(len(app.tabs), 0)
        self.assertTrue(any(
            "doğrulanmış kullanıcı oturumu yok" in item.message
            for item in app.error
        ))
        self.assertEqual(len(app.get("button")), 0)

    @patch.object(ct, "render_scoped_company_workspace")
    @patch.object(ct, "scoped_company_view_enabled", return_value=False)
    @patch.object(ct, "company_review_mode_state", return_value="invalid")
    @patch.object(ct, "login_gate", return_value=True)
    @patch.object(ct, "st")
    def test_control_tower_direct_invalid_mode_also_blocks(
        self, st, login, mode, view, scoped_render,
    ):
        ct._render_control_tower_interface(live_postgres=True)
        scoped_render.assert_not_called()
        st.tabs.assert_not_called()
        st.error.assert_called_once()

    @patch.object(ct, "init_security_tables")
    @patch.object(ct, "init_db")
    @patch.object(ct, "render_scoped_company_workspace")
    @patch.object(ct, "scoped_company_view_enabled", return_value=True)
    @patch.object(ct, "company_review_mode_state", return_value="review")
    @patch.object(ct, "login_gate", return_value=True)
    @patch.object(ct, "st")
    def test_control_tower_direct_sqlite_fallback_blocked_in_review_mode(
        self, st, login, mode, view, scoped_render, init_db, init_sec,
    ):
        ct._render_control_tower_interface(live_postgres=False)
        scoped_render.assert_not_called()
        st.tabs.assert_not_called()
        st.error.assert_called_once()


if __name__ == "__main__":
    unittest.main()
