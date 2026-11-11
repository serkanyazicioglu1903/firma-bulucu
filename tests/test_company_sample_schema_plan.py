"""Schema proposal must never silently expose tenant sample records."""
import unittest
from scripts.company_sample_schema_plan import SAMPLE_TABLE_SQL, SAMPLE_SECURITY_REQUIREMENTS

class SampleSchemaPlanTests(unittest.TestCase):
    def test_denies_public_access(self):
        sql = SAMPLE_TABLE_SQL.upper()
        self.assertIn("LEGAL_ENTITY_ID BIGINT NOT NULL", sql)
        self.assertIn("ENABLE ROW LEVEL SECURITY", sql)
        self.assertIn("FORCE ROW LEVEL SECURITY", sql)
        self.assertIn("REVOKE ALL ON CT_APP.COMPANY_SAMPLES FROM PUBLIC, ANON, AUTHENTICATED", sql)
        self.assertNotIn("GRANT SELECT", sql)
        self.assertNotIn("GRANT INSERT", sql)
        self.assertNotIn("CREATE POLICY", sql)

    def test_requires_security_review_before_activation(self):
        self.assertGreaterEqual(len(SAMPLE_SECURITY_REQUIREMENTS), 6)

if __name__ == "__main__":
    unittest.main()
