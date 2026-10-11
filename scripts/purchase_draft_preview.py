"""Prepare an unapproved purchase order draft from a MANUALLY calculated quote.

Strictly offline and session-only. This is a CSV export to a human reviewer,
not a saved PostgreSQL/SQLite order, not a supplier commitment and not proof
of company-specific authorization. No demo, DB imports, network or file IO.
"""
import csv
from decimal import Decimal, InvalidOperation
from io import StringIO

from scripts.group_company_catalog import COMPANY_LABELS
from scripts.real_quote_estimator import CURRENCIES


class PurchaseDraftError(ValueError):
    def __init__(self, code="invalid_draft"):
        self.code = code
        super().__init__(code)


def _safe_text(value, *, required=True, max_length=150):
    """Reject spreadsheet formulas and line/control characters, never echo values."""
    if not isinstance(value, str):
        raise PurchaseDraftError("invalid_text")
    text = value.strip()
    if required and not text:
        raise PurchaseDraftError("required_text")
    if len(text) > max_length or any(ord(char) < 32 or ord(char) == 127 for char in text):
        raise PurchaseDraftError("invalid_text")
    if text and text[0] in "=+-@":
        raise PurchaseDraftError("unsafe_csv_text")
    return text


def _decimal(value, *, positive=True):
    if type(value) is bool or value is None:
        raise PurchaseDraftError("invalid_amount")
    try:
        amount = Decimal(str(value))
    except (ValueError, InvalidOperation, TypeError):
        raise PurchaseDraftError("invalid_amount") from None
    if not amount.is_finite() or (amount <= 0 if positive else amount < 0):
        raise PurchaseDraftError("invalid_amount")
    return amount


def _percent(value):
    result = _decimal(value, positive=False)
    if result > 100:
        raise PurchaseDraftError("invalid_percent")
    return result


def _days(value):
    # The quote estimator outputs Decimal days, unlike the UI's int inputs.
    number = _decimal(value, positive=False)
    if number != number.to_integral_value() or number > 3650:
        raise PurchaseDraftError("invalid_days")
    return number


def purchase_draft_csv(quote, *, company_code, supplier, product_name,
                       warehouse_name, internal_reference=""):
    """Freeze one selected company's calculated purchase inputs into review CSV.

    The company is a display tag ONLY: server-verified grants/legal IDs are
    required in a future separately approved transactional workflow. Never
    infer a supplier, product master, warehouse ID or legal owner.
    """
    if not isinstance(quote, dict):
        raise PurchaseDraftError("missing_quote")
    if (not isinstance(company_code, str)
            or company_code not in COMPANY_LABELS
            or quote.get("company_code") != company_code):
        raise PurchaseDraftError("company_changed")
    vendor = _safe_text(supplier)
    product = _safe_text(product_name)
    warehouse = _safe_text(warehouse_name)
    reference = _safe_text(internal_reference, required=False, max_length=80)
    buy = quote.get("buy_currency")
    base = quote.get("base_currency")
    sell = quote.get("sell_currency")
    if any(ccy not in CURRENCIES for ccy in (buy, base, sell)):
        raise PurchaseDraftError("invalid_currency")

    qty = _decimal(quote.get("quantity_kg"))
    price = _decimal(quote.get("buy_price_per_kg"))
    fx = _decimal(quote.get("buy_fx_to_base"))
    goods_base = _decimal(quote.get("goods_base"))
    landed = _decimal(quote.get("landed_total_base"))
    cost = _decimal(quote.get("total_cost_base"))
    target_sell = _decimal(quote.get("required_sell_price"))
    deposit = _percent(quote.get("prepayment_pct"))
    lead = _days(quote.get("prepayment_lead_days"))
    balance = _days(quote.get("supplier_balance_due_days"))
    if (goods_base != qty * price * fx or
            (buy == base and fx != 1) or landed < goods_base or cost < landed):
        raise PurchaseDraftError("quote_inconsistent")

    output = StringIO()
    writer = csv.writer(output)
    writer.writerow(("Alan", "Değer", "Birim"))
    fields = (
        ("Durum", "ONAYSIZ TASLAK - SİPARİŞ OLUŞTURULMADI", ""),
        ("Şirket kodu - yalnızca etiket", company_code, ""),
        ("Şirket etiketi - hukuki unvan doğrulanmadı", COMPANY_LABELS[company_code], ""),
        ("Tedarikçi - manuel", vendor, ""),
        ("Ürün - manuel", product, ""),
        ("Teslim deposu - manuel", warehouse, ""),
        ("İç referans", reference, ""),
        ("Miktar", qty, "kg"),
        ("Tedarikçi alış birim fiyatı", price, buy + "/kg"),
        ("Tedarikçi mal bedeli", qty * price, buy),
        ("Manuel alış kuru", fx, "1 " + buy + " = " + base),
        ("Mal bedeli hesap para birimi", goods_base, base),
        ("Tahmini ithal maliyet", landed, base),
        ("Tahmini finansman dahil toplam maliyet", cost, base),
        ("Tedarikçi ön ödeme", deposit, "%"),
        ("Ön ödeme-varış süresi", lead, "gün"),
        ("Kalan ödeme varıştan sonra", balance, "gün"),
        ("Hedef satış fiyatı", target_sell, sell + "/kg"),
        ("Uyarı", "İmza, satın alma yetkisi, depo, vergi ve ticari şartlar ayrıca doğrulanmalı", ""),
        ("Kayıt", "Veritabanına yazılmadı; gerçek PO numarası oluşmadı", ""),
    )
    for label, value, unit in fields:
        writer.writerow((label, str(value), unit))
    return output.getvalue().encode("utf-8-sig")
