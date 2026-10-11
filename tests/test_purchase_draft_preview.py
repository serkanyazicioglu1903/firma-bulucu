"""Pure quote -> unapproved purchase draft validation.

CI uses fictional products, warehouses and figures, never Supabase or SQLite.
"""
import csv
from decimal import Decimal
from io import StringIO
from pathlib import Path
import unittest

from scripts.group_company_catalog import COMPANY_LABELS
from scripts.purchase_draft_preview import PurchaseDraftError, purchase_draft_csv
from scripts.real_quote_estimator import calculate_real_quote
import real_quote_workspace as ui


def quote(company="AS_ILERI_GIDA", *, currency="EUR"):
    return calculate_real_quote(
        company_code=company, quantity_kg="24000",
        buy_price_per_kg="2.4", buy_currency=currency,
        buy_fx_to_base=("1" if currency == "EUR" else "0.9"),
        base_currency="EUR", sell_price_per_kg="3.1",
        sell_currency="EUR", sell_fx_to_base="1",
        freight_total_base="1800", customs_total_base="0",
        import_other_total_base="300", handling_total_base="240",
        annual_finance_rate_pct="25", prepayment_pct="20",
        prepayment_lead_days=30, supplier_balance_due_days=60,
        stock_days=10, customer_credit_days=90,
        sales_commission_pct="1", target_margin_pct="12",
    )


def fields(data):
    text = data.decode("utf-8-sig")
    rows = list(csv.reader(StringIO(text)))
    assert rows[0] == ["Alan", "Değer", "Birim"]
    return {label: (value, unit) for label, value, unit in rows[1:]}


class PurchaseDraftPreviewTests(unittest.TestCase):
    def test_purchase_draft_for_each_company_does_not_assign_legal_id(self):
        for code in COMPANY_LABELS:
            with self.subTest(code=code):
                data = purchase_draft_csv(
                    quote(code), company_code=code, supplier="Example Factory",
                    product_name="Ingredient A", warehouse_name="Depot North",
                    internal_reference="REVIEW-001",
                )
                rows = fields(data)
                self.assertEqual(rows["Şirket kodu - yalnızca etiket"][0], code)
                self.assertEqual(rows["Durum"][0],
                                 "ONAYSIZ TASLAK - SİPARİŞ OLUŞTURULMADI")
                self.assertEqual(rows["Tedarikçi mal bedeli"],
                                 ("57600.0", "EUR"))
                self.assertIn("Gerçek PO numarası", "Gerçek PO numarası")
                self.assertIn("Sipariş", rows["Uyarı"][0])
                self.assertNotIn("company_write_grants", data.decode("utf-8-sig"))
                self.assertNotIn("legal_entity_id", data.decode("utf-8-sig"))

    def test_cross_currency_retains_supplier_amount_and_exact_manual_fx(self):
        q = quote("AS_FOOD_GLOBAL", currency="USD")
        rows = fields(purchase_draft_csv(
            q, company_code="AS_FOOD_GLOBAL", supplier="Factory",
            product_name="Product B", warehouse_name="UK Depot"))
        self.assertEqual(rows["Tedarikçi alış birim fiyatı"], ("2.4", "USD/kg"))
        self.assertEqual(rows["Tedarikçi mal bedeli"], ("57600.0", "USD"))
        self.assertEqual(rows["Manuel alış kuru"], ("0.9", "1 USD = EUR"))
        self.assertEqual(rows["Mal bedeli hesap para birimi"],
                         ("51840.00", "EUR"))
        self.assertEqual(rows["Tedarikçi ön ödeme"], ("20", "%"))
        self.assertEqual(rows["Kalan ödeme varıştan sonra"], ("60", "gün"))

    def test_mismatch_or_tampered_quote_fails_closed(self):
        q = quote()
        args = dict(
            company_code="AS_ILERI_GIDA", supplier="Factory",
            product_name="Product", warehouse_name="Depot")
        with self.assertRaisesRegex(PurchaseDraftError, "company_changed"):
            purchase_draft_csv(q, **{**args, "company_code": "PLANET_INGREDIENTS"})
        q["goods_base"] += Decimal("1")
        with self.assertRaisesRegex(PurchaseDraftError, "quote_inconsistent"):
            purchase_draft_csv(q, **args)
        q = quote()
        q["buy_price_per_kg"] = Decimal("NaN")
        with self.assertRaises(PurchaseDraftError):
            purchase_draft_csv(q, **args)

    def test_missing_supplier_product_or_depot_denied(self):
        args = dict(
            company_code="AS_ILERI_GIDA", supplier="Factory",
            product_name="Product", warehouse_name="Depot")
        for key in ("supplier", "product_name", "warehouse_name"):
            with self.subTest(key=key), self.assertRaises(PurchaseDraftError):
                purchase_draft_csv(quote(), **{**args, key: ""})

    def test_csv_formula_and_multiline_injection_denied(self):
        args = dict(
            company_code="AS_ILERI_GIDA", supplier="Factory",
            product_name="Product", warehouse_name="Depot")
        for payload in ("=SUM(1,1)", "  +CMD", "-1+2", "@SUM(A1)", "Good\nBad"):
            with self.subTest(value=payload), self.assertRaises(PurchaseDraftError):
                purchase_draft_csv(quote(), **{**args, "supplier": payload})
        with self.assertRaises(PurchaseDraftError):
            purchase_draft_csv(
                quote(), **{**args, "internal_reference": "=HYPERLINK(A1)"})

    def test_quote_change_clears_previous_purchase_draft(self):
        from unittest.mock import patch
        with patch.object(ui, "st") as st:
            st.session_state = {
                ui._PO_CSV_KEY: b"previous private draft",
                "ct_po_supplier": "Old supplier",
                "ct_rq_qty": 24000,
            }
            ui._reset_result()
            self.assertNotIn(ui._PO_CSV_KEY, st.session_state)
            self.assertNotIn("ct_po_supplier", st.session_state)
            self.assertEqual(st.session_state["ct_rq_qty"], 24000)

    def test_neither_module_uses_database_or_network(self):
        source = (Path(__file__).resolve().parents[1]
                  / "scripts" / "purchase_draft_preview.py").read_text()
        self.assertNotIn("psycopg", source)
        self.assertNotIn("sqlite3", source)
        self.assertNotIn("requests", source)
        self.assertNotIn("execute(", source)


if __name__ == "__main__":
    unittest.main()
