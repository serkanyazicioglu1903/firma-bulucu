"""Printable Turkish sample information form; never invents legal company details."""
from io import BytesIO
from xml.sax.saxutils import escape
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle

FONT = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"
FONT_BOLD = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"


def make_sample_pdf(record):
    """Produce a one-page or flowing printable form from an explicit record."""
    pdfmetrics.registerFont(TTFont("SampleDejaVu", FONT))
    pdfmetrics.registerFont(TTFont("SampleDejaVuBold", FONT_BOLD))
    buffer = BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=A4, leftMargin=17*mm, rightMargin=17*mm,
                            topMargin=18*mm, bottomMargin=17*mm)
    styles = getSampleStyleSheet()
    body = ParagraphStyle("SampleBody", parent=styles["Normal"], fontName="SampleDejaVu",
                          fontSize=9, leading=14, spaceAfter=0)
    heading = ParagraphStyle("SampleTitle", parent=body, fontName="SampleDejaVuBold",
                             fontSize=16, leading=23, alignment=TA_CENTER)
    story = [Paragraph("NUMUNE BİLGİ VE TAKİP FORMU", heading), Spacer(1, 10*mm)]
    fields = [
        ("Müşteri firma", "Firma"), ("İlgili kişi", "Yetkili"), ("Ürün adı", "Ürün"),
        ("Üretici / tedarikçi", "Üretici"), ("Lot / parti", "Lot"),
        ("Numune miktarı", None), ("Gönderim tarihi", "Gönderim"),
        ("Kargo firması", "Kargo"), ("Kargo takip no", "Takip"),
        ("Planlanan deneme", "Deneme tarihi"), ("Uygulama", "Uygulama"),
        ("Durum", "Durum"), ("Tahmini yıllık tüketim", "Yıllık tüketim"),
        ("Deneme sonucu / notlar", "Not"),
    ]
    rows = []
    for label, key in fields:
        value = str(record.get(key, "") or "") if key else f'{record.get("Miktar", "")} {record.get("Birim", "")}'
        rows.append([Paragraph(escape(label), body), Paragraph(escape(value), body)])
    table = Table(rows, colWidths=[54*mm, 122*mm], hAlign="LEFT", repeatRows=0)
    table.setStyle(TableStyle([
        ("VALIGN", (0,0),(-1,-1),"TOP"),
        ("BACKGROUND",(0,0),(0,-1),colors.HexColor("#f0f3f6")),
        ("GRID",(0,0),(-1,-1),0.35,colors.HexColor("#d7dde4")),
        ("LEFTPADDING",(0,0),(-1,-1),8),
        ("RIGHTPADDING",(0,0),(-1,-1),8),
        ("TOPPADDING",(0,0),(-1,-1),7),
        ("BOTTOMPADDING",(0,0),(-1,-1),7),
    ]))
    story.append(table)
    doc.build(story)
    return buffer.getvalue()
