"""Regression tests for the iPad quote route; no database/network writes."""
import unittest
from pathlib import Path

from streamlit.testing.v1 import AppTest


APP = Path(__file__).resolve().parents[1] / "app.py"


def signed_preview():
    at = AppTest.from_file(APP, default_timeout=90)
    at.secrets["CONTROL_TOWER_PASSWORD"] = "ci-test-password"
    at.session_state["ct_user"] = {
        "username": "ci-admin", "display_name": "CI Admin", "role": "ADMIN",
    }
    at.session_state["ct_session_id"] = "ci-signed-session"
    return at


class QuoteFastRouteTests(unittest.TestCase):
    def test_isolated_quote_screen_renders_real_inputs_without_legacy_tabs(self):
        at = signed_preview()
        at.query_params["page"] = "quote"
        at.run()
        self.assertFalse(at.exception, str(at.exception))
        self.assertFalse(at.tabs, "isolated quote page should skip heavy legacy tabs")
        labels = {widget.label for widget in at.number_input}
        self.assertIn("Miktar (kg)", labels)
        self.assertTrue(any("Alış fiyatı" in label for label in labels))
        self.assertTrue(any("Navlun" in label for label in labels))
        self.assertTrue(any("Müşteri tahsilat vadesi" in label for label in labels))
        self.assertTrue(any("Hedef net katkı marjı" in label for label in labels))

    def test_quote_route_does_not_bypass_login_gate(self):
        at = AppTest.from_file(APP, default_timeout=60)
        at.secrets["CONTROL_TOWER_PASSWORD"] = "ci-test-password"
        at.query_params["page"] = "quote"
        at.run()
        self.assertFalse(at.exception, str(at.exception))
        self.assertTrue(any("Giriş" in b.label for b in at.button))
        self.assertFalse(any(w.label == "Miktar (kg)" for w in at.number_input))

    def test_main_quote_tab_is_rendered_before_heavy_control_tower(self):
        text = APP.read_text(encoding="utf-8")
        self.assertLess(text.index('if not login_gate():'), text.index('if st.query_params.get("page") == "quote":'))
        self.assertLess(text.index('if review_mode != "disabled":'), text.index('if st.query_params.get("page") == "quote":'))
        tab_section = text[text.index("main_tab1, main_tab2, main_tab3, main_tab4"): ]
        self.assertLess(tab_section.index("with main_tab4:"), tab_section.index("with main_tab3:"))
        self.assertIn("render_real_quote_workspace()", tab_section)


if __name__ == "__main__":
    unittest.main()
