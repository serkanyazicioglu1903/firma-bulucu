"""Regression tests for independent real quote route (no business DB).

Each Streamlit AppTest executes in a fresh process because other tests can
leave an AppTest form context active in the parent unittest interpreter.
"""
import os
from pathlib import Path
import subprocess
import sys
import unittest


ROOT = Path(__file__).resolve().parents[1]
PAGE = ROOT / "pages" / "01_real_quote.py"


class StandaloneQuotePageTests(unittest.TestCase):
    def test_quote_is_rendered_before_large_control_tower(self):
        source = (ROOT / "app.py").read_text(encoding="utf-8")
        self.assertLess(source.index("with main_tab4:"), source.index("with main_tab3:"))
        self.assertEqual(source.count("render_real_quote_workspace()"), 1)
        self.assertIn('"pages/01_real_quote.py"', source)

    def _run_page_fresh_process(self, role, mode):
        script = r'''
import os
from streamlit.testing.v1 import AppTest

app = AppTest.from_file("pages/01_real_quote.py", default_timeout=45)
app.session_state["ct_user"] = {
    "username": "fictional-operator", "display_name": "CI",
    "role": os.environ["QUOTE_CI_ROLE"],
}
app.session_state["ct_session_id"] = "fictional-session"
app.run()
assert not app.exception, str(app.exception)
if os.environ["QUOTE_CI_MODE"] == "REVIEW_ONLY_WITH_SIGNED_SESSION":
    assert len(app.get("number_input")) == 0
    assert any("güvenlik" in e.value.lower() for e in app.error)
elif os.environ["QUOTE_CI_ROLE"] == "VIEWER":
    assert len(app.get("number_input")) == 0
    assert any("erişimi" in w.value.lower() for w in app.warning)
else:
    assert any("Gerçek Teklif" in item.value for item in app.title)
    fields = app.get("number_input")
    assert len(fields) >= 10, len(fields)
    assert all(item.value == 0 or item.value == 0.0 for item in fields)
    assert len(app.get("download_button")) == 0
print("STANDALONE_QUOTE_OK")
'''
        env = dict(os.environ)
        env["QUOTE_CI_ROLE"] = role
        env["QUOTE_CI_MODE"] = mode
        env["CT_COMPANY_SCOPED_VIEW_MODE"] = mode
        # CI supplies a synthetic secrets.toml password; no production secrets.
        outcome = subprocess.run(
            [sys.executable, "-c", script], cwd=ROOT, env=env,
            text=True, capture_output=True, timeout=85, check=False,
        )
        self.assertEqual(
            outcome.returncode, 0,
            (outcome.stdout + "\n" + outcome.stderr)[-5500:],
        )
        self.assertIn("STANDALONE_QUOTE_OK", outcome.stdout)

    def test_isolated_page_shows_zero_input_quote_controls(self):
        self._run_page_fresh_process("ADMIN", "")

    def test_viewer_cannot_open_quote_controls_on_direct_url(self):
        self._run_page_fresh_process("VIEWER", "")

    def test_company_review_blocks_direct_page_access(self):
        self._run_page_fresh_process("ADMIN", "REVIEW_ONLY_WITH_SIGNED_SESSION")


if __name__ == "__main__":
    unittest.main()
