"""Smoke test: the purchase draft follows a calculated quote in Streamlit.

Runs isolated with fictional data; no real DB, secrets, or business writes.
"""
import os
from pathlib import Path
import subprocess
import sys
import unittest


ROOT = Path(__file__).resolve().parents[1]


class PurchaseDraftUiTests(unittest.TestCase):
    def test_draft_form_requires_calculated_quote_and_does_not_autosave(self):
        script = r'''
from streamlit.testing.v1 import AppTest
from scripts.real_quote_estimator import calculate_real_quote

app = AppTest.from_file("pages/01_real_quote.py", default_timeout=60)
app.session_state["ct_user"] = {
    "username": "ci-operator", "display_name": "CI", "role": "ADMIN"
}
app.session_state["ct_session_id"] = "only-in-ci"
app.run()
assert not app.exception, str(app.exception)
assert not any("Tedarikçi adı (manuel)" == item.label
               for item in app.get("text_input"))
app.session_state["ct_real_quote_result"] = calculate_real_quote(
    company_code="AS_ILERI_GIDA", quantity_kg=1000,
    buy_price_per_kg=2, buy_currency="EUR", buy_fx_to_base=1,
    base_currency="EUR", sell_price_per_kg=0, sell_currency="EUR",
    sell_fx_to_base=1, freight_total_base=100,
    annual_finance_rate_pct=0, prepayment_pct=0, prepayment_lead_days=0,
    supplier_balance_due_days=0, stock_days=0, customer_credit_days=0,
    sales_commission_pct=0, target_margin_pct=12,
)
app.run()
assert not app.exception, str(app.exception)
assert any("Tedarikçi adı (manuel)" == item.label
           for item in app.get("text_input"))
assert any("Teslim deposu / yeri (manuel)" == item.label
           for item in app.get("text_input"))
assert not any("Satın alma taslağını CSV indir" in btn.label
               for btn in app.get("button"))
assert "ct_purchase_draft_csv" not in app.session_state
print("PO_DRAFT_UI_OK")
'''
        env = dict(os.environ)
        env["CT_COMPANY_SCOPED_VIEW_MODE"] = ""
        env.pop("AS_CONTROL_TOWER_DEMO_SEED", None)
        process = subprocess.run(
            [sys.executable, "-c", script], cwd=ROOT, env=env,
            capture_output=True, text=True, timeout=90, check=False,
        )
        self.assertEqual(process.returncode, 0,
                         (process.stdout + "\n" + process.stderr)[-6000:])
        self.assertIn("PO_DRAFT_UI_OK", process.stdout)


if __name__ == "__main__":
    unittest.main()
