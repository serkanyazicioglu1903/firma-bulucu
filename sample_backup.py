"""Validate explicitly uploaded sample tracking JSON before session restore.

No database operations and no implicit imports. This is a temporary manual
recovery path until per-company persistence is implemented and audited.
"""
import json
import math
from datetime import date

FIELDS = ("Firma", "Yetkili", "Ürün", "Üretici", "Lot", "Miktar", "Birim",
          "Gönderim", "Kargo", "Takip", "Deneme tarihi", "Uygulama",
          "Durum", "Yıllık tüketim", "Not")
VALID_UNITS = {"kg", "g", "adet", "L", "mL"}
VALID_STATUSES = {"Talep alındı", "Hazırlanıyor", "Gönderildi", "Teslim edildi",
                  "Denemede", "Onaylandı", "Başarısız", "Siparişe dönüştü"}


def parse_sample_backup(raw):
    if not isinstance(raw, bytes) or len(raw) > 1024 * 1024:
        raise ValueError("invalid_sample_backup")
    try:
        data = json.loads(raw.decode("utf-8"))
        if not isinstance(data, list) or len(data) > 500:
            raise ValueError()
        cleaned = []
        for item in data:
            if not isinstance(item, dict) or set(item) != set(FIELDS):
                raise ValueError()
            row = {}
            for field in FIELDS:
                value = item[field]
                if field == "Miktar":
                    if isinstance(value, bool) or not isinstance(value, (int, float)):
                        raise ValueError()
                    if not math.isfinite(value) or value < 0 or value > 100000000:
                        raise ValueError()
                    row[field] = value
                else:
                    if not isinstance(value, str) or len(value) > 2000:
                        raise ValueError()
                    row[field] = value
            if not row["Firma"].strip() or not row["Ürün"].strip():
                raise ValueError()
            if row["Birim"] not in VALID_UNITS or row["Durum"] not in VALID_STATUSES:
                raise ValueError()
            date.fromisoformat(row["Gönderim"])
            date.fromisoformat(row["Deneme tarihi"])
            cleaned.append(row)
        return cleaned
    except (ValueError, UnicodeError, TypeError, KeyError, OverflowError) as exc:
        raise ValueError("invalid_sample_backup") from exc
