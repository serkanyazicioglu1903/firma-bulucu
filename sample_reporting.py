"""Pure helpers for sample follow-up dashboards (no database writes)."""
import csv
from datetime import date
from io import StringIO

CLOSED_STATUSES = frozenset({"Onaylandı", "Başarısız", "Siparişe dönüştü"})

def is_overdue(record, today=None):
    """Invalid or missing dates are not treated as overdue."""
    today = today or date.today()
    if record.get("Durum") in CLOSED_STATUSES:
        return False
    try:
        return date.fromisoformat(str(record.get("Deneme tarihi", ""))) < today
    except (TypeError, ValueError):
        return False

def filter_samples(records, search="", status="Tümü", supplier="Tümü", overdue_only=False, today=None):
    """Return original list indices to preserve correct PDF/edit selection."""
    term = search.strip().casefold()
    filtered = []
    for index, record in enumerate(records):
        if term and not any(term in str(record.get(k, "")).casefold()
                            for k in ("Firma", "Ürün", "Yetkili", "Üretici", "Not")):
            continue
        if status != "Tümü" and record.get("Durum") != status:
            continue
        if supplier != "Tümü" and record.get("Üretici") != supplier:
            continue
        if overdue_only and not is_overdue(record, today):
            continue
        filtered.append(index)
    return filtered

def sample_summary(records, today=None):
    return {
        "total": len(records),
        "overdue": sum(is_overdue(record, today) for record in records),
        "in_trial": sum(record.get("Durum") == "Denemede" for record in records),
        "approved": sum(record.get("Durum") == "Onaylandı" for record in records),
    }

def samples_csv(records):
    """Excel-compatible CSV, preserving Turkish characters and safe column order."""
    fields = ["Firma", "Yetkili", "Ürün", "Üretici", "Lot", "Miktar", "Birim",
              "Gönderim", "Kargo", "Takip", "Deneme tarihi", "Uygulama",
              "Durum", "Yıllık tüketim", "Not"]
    out = StringIO()
    writer = csv.DictWriter(out, fieldnames=fields, extrasaction="ignore")
    writer.writeheader()
    for record in records:
        # Prevent spreadsheet formula injection in untrusted text.
        safe = {}
        for key in fields:
            value = record.get(key, "")
            if isinstance(value, str) and value.lstrip().startswith(("=", "+", "-", "@")):
                value = "'" + value
            safe[key] = value
        writer.writerow(safe)
    return out.getvalue().encode("utf-8-sig")
