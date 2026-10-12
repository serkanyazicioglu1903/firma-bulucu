"""Static safety checks for quote-first routing; no Streamlit global state."""
import unittest
from pathlib import Path

APP = Path(__file__).resolve().parents[1] / "app.py"


class QuoteRouteSafetyTests(unittest.TestCase):
    def test_standalone_route_keeps_login_and_exclusive_review_guard(self):
        source = APP.read_text(encoding="utf-8")
        login = source.index("if not login_gate():")
        review = source.index('if review_mode != "disabled":')
        direct = source.index('if st.query_params.get("page") == "quote":')
        legacy = source.index("main_tab1, main_tab2, main_tab3, main_tab4")
        self.assertLess(login, review)
        self.assertLess(review, direct)
        self.assertLess(direct, legacy)
        standalone = source[direct:legacy]
        self.assertIn("render_real_quote_workspace()", standalone)
        self.assertIn("st.stop()", standalone)

    def test_main_quote_tab_is_rendered_before_heavy_control_tower(self):
        source = APP.read_text(encoding="utf-8")
        tabs = source[source.index("main_tab1, main_tab2, main_tab3, main_tab4"):]
        self.assertLess(tabs.index("with main_tab4:"), tabs.index("with main_tab3:"))
        self.assertIn("render_real_quote_workspace()", tabs)


if __name__ == "__main__":
    unittest.main()
