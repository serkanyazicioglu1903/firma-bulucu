"""Regression tests: isolated quote page must paint controls without legacy tabs.

No real company data, PostgreSQL credentials or write operations are used.
"""
import os
from pathlib import Path
import unittest
from unittest.mock import patch

from streamlit.testing.v1 import AppTest


ROOT = Path(__file__).resolve().parents[1]
STANDALONE_PAGE = ROOT / "pages" / "01_real_quote.py"


class StandaloneQuotePageTests(unittest.TestCase):
    def test_quote_is_rendered_before_large_control_tower(self):
        source = (ROOT / "app.py").read_text(encoding="utf-8")
        self.assertLess(
            source.index("with main_tab4:"),
            source.index("with main_tab3:"),
        )
        self.assertEqual(source.count("render_real_quote_workspace()"), 1)
        self.assertIn('st.page_link(\n        "pages/01_real_quote.py"', source)

    def _run_page(self, role="ADMIN"):
        with patch.dict(os.environ, {"CT_COMPANY_SCOPED_VIEW_MODE": ""}):
            app = AppTest.from_file(str(STANDALONE_PAGE), default_timeout=45)
            app.session_state["ct_user"] = {
                "username": "fictional-user",
                "display_name": "CI",
                "role": role,
            }
            app.session_state["ct_session_id"] = "fictional-session"
            app.run()
        return app

    def test_isolated_page_shows_quote_form_and_all_zero_inputs(self):
        app = self._run_page()
        self.assertFalse(app.exception, str(app.exception))
        self.assertTrue(any("Gerçek Teklif" in item.value for item in app.title))
        self.assertGreaterEqual(len(app.get("number_input")), 10)
        self.assertEqual(len(app.get("form")), 1)
        self.assertEqual(len(app.get("download_button")), 0)
        self.assertTrue(all(
            item.value == 0 or item.value == 0.0
            for item in app.get("number_input")
        ))

    def test_viewer_cannot_open_quote_controls_on_direct_url(self):
        app = self._run_page("VIEWER")
        self.assertFalse(app.exception, str(app.exception))
        self.assertEqual(len(app.get("number_input")), 0)
        self.assertEqual(len(app.get("form")), 0)
        self.assertTrue(any(
            "erişimi" in item.value.lower() for item in app.warning
        ))

    def test_company_review_blocks_direct_page_access(self):
        with patch.dict(os.environ, {
            "CT_COMPANY_SCOPED_VIEW_MODE": "REVIEW_ONLY_WITH_SIGNED_SESSION",
        }):
            app = AppTest.from_file(str(STANDALONE_PAGE), default_timeout=45)
            app.session_state["ct_user"] = {
                "username": "fictional-user",
                "display_name": "CI",
                "role": "ADMIN",
            }
            app.session_state["ct_session_id"] = "fictional-session"
            app.run()
        self.assertFalse(app.exception, str(app.exception))
        self.assertEqual(len(app.get("number_input")), 0)
        self.assertTrue(any("güvenlik" in error.value.lower() for error in app.error))


if __name__ == "__main__":
    unittest.main()
