import json
import unittest
from sample_backup import parse_sample_backup

ROW = {"Firma":"Ülker","Yetkili":"","Ürün":"Pantur 1250","Üretici":"",
       "Lot":"","Miktar":1.0,"Birim":"kg","Gönderim":"2026-10-24",
       "Kargo":"","Takip":"","Deneme tarihi":"2026-11-07","Uygulama":"",
       "Durum":"Denemede","Yıllık tüketim":"","Not":""}

class SampleBackupTests(unittest.TestCase):
    def test_valid_roundtrip(self):
        self.assertEqual(parse_sample_backup(json.dumps([ROW]).encode()), [ROW])

    def test_rejects_missing_fields(self):
        with self.assertRaises(ValueError):
            parse_sample_backup(json.dumps([{"Firma":"A"}]).encode())

    def test_rejects_unsafe_quantity(self):
        bad = dict(ROW, Miktar=-1)
        with self.assertRaises(ValueError):
            parse_sample_backup(json.dumps([bad]).encode())

    def test_rejects_unknown_status(self):
        bad = dict(ROW, Durum="Unknown")
        with self.assertRaises(ValueError):
            parse_sample_backup(json.dumps([bad]).encode())

    def test_rejects_oversize(self):
        with self.assertRaises(ValueError):
            parse_sample_backup(b" " * (1024*1024+1))

if __name__ == "__main__":
    unittest.main()
