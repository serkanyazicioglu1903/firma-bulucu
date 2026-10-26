"""Regression tests for sample dashboard filters and exports."""
import csv
import io
import unittest
from datetime import date
from sample_reporting import filter_samples, sample_summary, samples_csv, is_overdue

RECORDS = [
    {"Firma":"Ülker", "Ürün":"Pantur", "Üretici":"Sonneveld", "Durum":"Denemede", "Deneme tarihi":"2026-10-20", "Not":"Takip"},
    {"Firma":"Katsan", "Ürün":"Agar", "Üretici":"ROKO", "Durum":"Onaylandı", "Deneme tarihi":"2026-10-01", "Not":"Tamam"},
    {"Firma":"Polen", "Ürün":"GMS", "Üretici":"ROKO", "Durum":"Gönderildi", "Deneme tarihi":"2026-11-10", "Not":"=2+2"},
]

class SampleReportingTests(unittest.TestCase):
    def test_closed_not_overdue(self):
        self.assertFalse(is_overdue(RECORDS[1], date(2026,10,26)))
        self.assertFalse(is_overdue({"Deneme tarihi":"bad", "Durum":"Denemede"}, date(2026,10,26)))

    def test_filter_keeps_original_indices(self):
        self.assertEqual(filter_samples(RECORDS, search="agar"), [1])
        self.assertEqual(filter_samples(RECORDS, supplier="ROKO"), [1,2])
        self.assertEqual(filter_samples(RECORDS, overdue_only=True, today=date(2026,10,26)), [0])

    def test_summary(self):
        self.assertEqual(sample_summary(RECORDS, date(2026,10,26)),
                         {"total":3, "overdue":1, "in_trial":1, "approved":1})

    def test_excel_csv_utf8_and_injection(self):
        content = samples_csv(RECORDS)
        self.assertTrue(content.startswith(b"\xef\xbb\xbf"))
        rows = list(csv.DictReader(io.StringIO(content.decode("utf-8-sig"))))
        self.assertEqual(rows[0]["Firma"], "Ülker")
        self.assertEqual(rows[2]["Not"], "'=2+2")

if __name__ == "__main__":
    unittest.main()
