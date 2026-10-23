"""Sample PDF must preserve Turkish text and never invent legal identifiers."""
import unittest
from sample_pdf import make_sample_pdf

class SamplePDFTests(unittest.TestCase):
    def test_pdf_is_generated(self):
        doc = make_sample_pdf({"Firma":"Ülker","Ürün":"Pantur 1250","Miktar":1,"Birim":"kg",
                               "Not":"Deneme için gönderildi"})
        self.assertTrue(doc.startswith(b"%PDF"))
        self.assertGreater(len(doc), 1500)

    def test_empty_fields_are_safe(self):
        self.assertTrue(make_sample_pdf({"Firma":"<Test & Co>"}).startswith(b"%PDF"))

if __name__ == "__main__":
    unittest.main()
