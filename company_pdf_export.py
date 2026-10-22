"""PDF exports for four-company demo quotes and orders.

Only explicit, company-scoped records are accepted. Never include unverified
company addresses, bank accounts, tax IDs, logos, or invented prices.
"""
from datetime import date
from decimal import Decimal, InvalidOperation
from io import BytesIO
from pathlib import Path
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT, TA_RIGHT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle

from scripts.group_company_catalog import COMPANY_LABELS

FONT_CANDIDATES = (
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    "/usr/share/fonts/truetype/liberation2/LiberationSans-Regular.ttf",
)
FONT_BOLD_CANDIDATES = (
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/truetype/liberation2/LiberationSans-Bold.ttf",
)
PACKAGING = ("25 kg torba", "200 kg varil", "1.000 kg IBC", "Özel")
PAYMENT = ("Peşin", "15 gün", "30 gün", "45 gün", "60 gün", "90 gün", "105 gün", "120 gün")
DELIVERY = ("Depodan", "Gümrükten", "Yolda")
LEAD_TIME = ("Hemen",) + tuple(f"{i} hafta" for i in range(1, 11))


def _fonts():
    if "CTPDFRegular" not in pdfmetrics.getRegisteredFontNames():
        regular = next((x for x in FONT_CANDIDATES if Path(x).is_file()), None)
        bold = next((x for x in FONT_BOLD_CANDIDATES if Path(x).is_file()), None)
        if not regular or not bold:
            raise RuntimeError("unicode_pdf_font_missing")
        pdfmetrics.registerFont(TTFont("CTPDFRegular", regular))
        pdfmetrics.registerFont(TTFont("CTPDFBold", bold))
    return "CTPDFRegular", "CTPDFBold"


def _safe(value, max_length=180):
    return escape(str(value or "")[:max_length])


def _money(amount):
    return f"{amount:,.2f}"


def _amount(value):
    try:
        d = Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        raise ValueError("invalid_amount") from None
    if not d.is_finite() or d < 0 or d > Decimal("1000000000000"):
        raise ValueError("invalid_amount")
    return d


def generate_company_pdf(*, company_code, kind, record, payment=None,
                         delivery=None, lead_time=None, packaging=None,
                         validity_days=14, discount_pct=0, vat_pct=0,
                         notes="", issued_on=None):
    if company_code not in COMPANY_LABELS or kind not in ("Teklifler", "Siparişler"):
        raise ValueError("invalid_document")
    if not isinstance(record, dict) or not record.get("reference"):
        raise ValueError("missing_record")
    if kind == "Teklifler":
        if payment not in PAYMENT or delivery not in DELIVERY or lead_time not in LEAD_TIME or packaging not in PACKAGING:
            raise ValueError("invalid_terms")
    discount, vat = _amount(discount_pct), _amount(vat_pct)
    if discount > 100 or vat > 100 or not 1 <= int(validity_days) <= 365:
        raise ValueError("invalid_terms")
    regular, bold = _fonts()
    styles = getSampleStyleSheet()
    title_style = ParagraphStyle("ct_pdf_title", parent=styles["Title"], fontName=bold,
                                 fontSize=17, leading=23, textColor=colors.HexColor("#152d48"))
    sub_style = ParagraphStyle("ct_pdf_sub", parent=styles["Normal"], fontName=regular,
                               fontSize=9, leading=14, textColor=colors.HexColor("#455a70"))
    body_style = ParagraphStyle("ct_pdf_body", parent=styles["Normal"], fontName=regular,
                                fontSize=9, leading=14)
    head_style = ParagraphStyle("ct_pdf_head", parent=body_style, fontName=bold)
    right_style = ParagraphStyle("ct_pdf_right", parent=body_style, alignment=TA_RIGHT)
    def p(value, style=body_style):
        return Paragraph(_safe(value), style)
    def line(label, value):
        return [p(label, head_style), p(value)]
    buffer = BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=A4, leftMargin=18*mm, rightMargin=18*mm,
                            topMargin=20*mm, bottomMargin=18*mm,
                            title=f"{COMPANY_LABELS[company_code]} - {kind} {record['reference']}")
    story = [
        p(COMPANY_LABELS[company_code], title_style),
        Spacer(1, 5*mm),
        p("FİYAT TEKLİFİ / QUOTATION" if kind == "Teklifler" else "SİPARİŞ FORMU / ORDER", head_style),
        Spacer(1, 3*mm),
    ]
    meta = [
        line("Referans", record["reference"]),
        line("Tarih", issued_on or date.today().isoformat()),
        line("Müşteri", record.get("customer", "")),
    ]
    if kind == "Teklifler":
        meta.append(line("Teklif geçerliliği", f"{int(validity_days)} gün"))
    else:
        meta.append(line("Sipariş durumu", record.get("status", "Belirtilmedi")))
    info = Table(meta, colWidths=[48*mm, 126*mm], hAlign="LEFT")
    info.setStyle(TableStyle([("VALIGN", (0,0), (-1,-1), "TOP"),
                              ("BOTTOMPADDING", (0,0), (-1,-1), 7)]))
    story.extend([info, Spacer(1, 5*mm)])
    qty = _amount(record.get("quantity_kg", 0))
    if kind == "Teklifler":
        price = _amount(record.get("unit_price", 0))
        ccy = str(record.get("currency") or "").upper()
        if ccy not in ("EUR", "USD", "GBP", "TRY", "TL"):
            raise ValueError("invalid_currency")
        subtotal = qty * price
        discount_amount = subtotal * discount / Decimal(100)
        net = subtotal - discount_amount
        vat_amount = net * vat / Decimal(100)
        total = net + vat_amount
        items = [
            [p("Ürün", head_style), p("Miktar (kg)", head_style),
             p(f"Birim fiyat ({ccy}/kg)", head_style), p(f"Tutar ({ccy})", head_style)],
            [p(record.get("product", "")), p(_money(qty), right_style),
             p(_money(price), right_style), p(_money(subtotal), right_style)],
        ]
        widths = [67*mm, 30*mm, 39*mm, 38*mm]
    else:
        items = [
            [p("Ürün", head_style), p("Miktar (kg)", head_style)],
            [p(record.get("product", "")), p(_money(qty), right_style)],
        ]
        widths = [120*mm, 54*mm]
    grid = Table(items, colWidths=widths, repeatRows=1, hAlign="LEFT")
    grid.setStyle(TableStyle([
        ("BACKGROUND", (0,0), (-1,0), colors.HexColor("#e9eff5")),
        ("GRID", (0,0), (-1,-1), .4, colors.HexColor("#d6dfe9")),
        ("VALIGN", (0,0), (-1,-1), "TOP"),
        ("TOPPADDING", (0,0), (-1,-1), 9),
        ("BOTTOMPADDING", (0,0), (-1,-1), 9),
    ]))
    story.extend([grid, Spacer(1, 6*mm)])
    if kind == "Teklifler":
        totals = [
            line("Ara toplam", f"{_money(subtotal)} {ccy}"),
            line(f"İskonto (%{discount})", f"-{_money(discount_amount)} {ccy}"),
            line(f"KDV (%{vat})", f"{_money(vat_amount)} {ccy}"),
            line("GENEL TOPLAM", f"{_money(total)} {ccy}"),
        ]
        t = Table(totals, colWidths=[110*mm, 64*mm])
        t.setStyle(TableStyle([
            ("LINEABOVE", (0,-1), (-1,-1), 1, colors.HexColor("#152d48")),
            ("VALIGN", (0,0), (-1,-1), "TOP"),
            ("BOTTOMPADDING", (0,0), (-1,-1), 7),
        ]))
        story.extend([t, Spacer(1, 6*mm)])
        conditions = [
            line("Ödeme", payment),
            line("Teslim şekli", delivery),
            line("Teslim süresi", lead_time),
            line("Ambalaj", packaging),
        ]
        terms = Table(conditions, colWidths=[48*mm, 126*mm])
        terms.setStyle(TableStyle([("BOTTOMPADDING", (0,0), (-1,-1), 6),
                                   ("VALIGN", (0,0), (-1,-1), "TOP")]))
        story.extend([p("TİCARİ KOŞULLAR", head_style), Spacer(1, 2*mm), terms])
    if notes:
        story.extend([Spacer(1, 5*mm), p("Notlar", head_style), p(notes[:1000])])
    story.extend([Spacer(1, 12*mm),
                  p("Belge uygulama içindeki seçili kayıttan oluşturulmuştur. "
                    "Banka ve iletişim bilgileri doğrulanmadığı için eklenmemiştir.", sub_style)])
    doc.build(story)
    return buffer.getvalue()
