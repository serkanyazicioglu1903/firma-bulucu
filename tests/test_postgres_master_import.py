"""Validation and fail-closed unit tests for company CSV imports.

All tests are offline. No production Supabase URL or real business records.
"""
import csv
from io import StringIO
import unittest
from unittest.mock import patch

from scripts import postgres_master_import as bulk

CI_URL = "postgresql://ct_ci:dummy@127.0.0.1:5432/ct_ci_control_tower"


def sample(domain, rows):
    output = StringIO(newline="")
    columns = bulk.DOMAINS[domain]["columns"]
    writer = csv.DictWriter(output, fieldnames=columns)
    writer.writeheader()
    for item in rows:
        writer.writerow(item)
    return output.getvalue().encode("utf-8")


class MasterImportValidationTests(unittest.TestCase):
    def test_all_templates_have_no_dummy_records_and_valid_headers(self):
        for domain, schema in bulk.DOMAINS.items():
            with self.subTest(domain=domain):
                data = bulk.template_csv(domain)
                self.assertTrue(data.startswith(b"\xef\xbb\xbf"))
                self.assertEqual(data.decode("utf-8-sig").count("\n"), 1)
                self.assertIn(schema["columns"][0], data.decode("utf-8-sig"))

    def test_user_csv_accepts_valid_realistic_records_and_applies_defaults(self):
        examples = {
            "Müşteriler": [{"name": "Onaylı Müşteri A", "sector": "Gıda"}],
            "Ürünler": [{"name": "Onaylı Ürün B", "supplier": "Onaylı Üretici B"}],
            "Depolar": [{"name": "Onaylı Depo C", "city": "İstanbul"}],
        }
        for domain, rows in examples.items():
            with self.subTest(domain=domain):
                result, parsed = bulk.parse_master_csv(sample(domain, rows), domain)
                self.assertEqual(result, "ok")
                self.assertEqual(len(parsed), 1)
                self.assertTrue(parsed[0]["name"].startswith("Onaylı "))
                self.assertEqual(set(parsed[0]), set(bulk.DOMAINS[domain]["columns"]))

    def test_missing_supplier_and_duplicate_names_rejected(self):
        self.assertEqual(
            bulk.parse_master_csv(
                sample("Ürünler", [{"name": "Kakao Tozu"}]),
                "Ürünler",
            )[0],
            "required_field_missing",
        )
        self.assertEqual(
            bulk.parse_master_csv(
                sample("Depolar", [{"name": "İstanbul"}, {"name": "İSTANBUL"}]),
                "Depolar",
            )[0],
            "duplicate_in_file",
        )

    def test_csv_rejects_injection_unknown_columns_and_limits(self):
        self.assertEqual(
            bulk.parse_master_csv(b"name,unknown\nTest,xxx\n", "Müşteriler")[0],
            "invalid_columns",
        )
        self.assertEqual(
            bulk.parse_master_csv(b"name,name\nA,B\n", "Müşteriler")[0],
            "invalid_columns",
        )
        self.assertEqual(
            bulk.parse_master_csv(b"name\nValue\x00Evil\n", "Müşteriler")[0],
            "invalid_file",
        )
        self.assertEqual(
            bulk.parse_master_csv(b"name\nInvalid\xff\n", "Müşteriler")[0],
            "invalid_csv",
        )
        self.assertEqual(
            bulk.parse_master_csv(b"name\n" + b"A\n" * 151, "Müşteriler")[0],
            "invalid_row_count",
        )
        self.assertEqual(
            bulk.parse_master_csv(b"name\n" + b"A" * (bulk.MAX_UPLOAD_BYTES + 1),
                                  "Müşteriler")[0],
            "invalid_file",
        )

    def test_country_warehouse_type_and_currency_validation(self):
        self.assertEqual(
            bulk.parse_master_csv(
                sample("Depolar", [{"name": "A", "warehouse_type": "NotWarehouse"}]),
                "Depolar",
            )[0], "invalid_warehouse_type",
        )
        self.assertEqual(
            bulk.parse_master_csv(
                sample("Ürünler", [{"name": "A", "supplier": "B",
                                    "default_currency": "BTC"}]),
                "Ürünler",
            )[0], "invalid_currency",
        )
        self.assertEqual(
            bulk.parse_master_csv(
                sample("Müşteriler", [{"name": "A", "status": "DONE"}]),
                "Müşteriler",
            )[0], "invalid_customer_status",
        )

    @patch.object(bulk, "validate_staging_structure")
    def test_without_explicit_backup_and_phrase_no_db_checks(self, schema):
        for kw in (
            {"confirmation": "", "backup_confirmed": True},
            {"confirmation": bulk.APPROVAL, "backup_confirmed": False},
        ):
            with self.subTest(**kw):
                self.assertEqual(
                    bulk.import_new_masters(
                        CI_URL, role="ADMIN", actor="ci-admin",
                        domain="Müşteriler", rows=[{"name": "Dummy"}], **kw,
                    ),
                    ("not_confirmed", 0),
                )
        schema.assert_not_called()

    @patch.object(bulk, "validate_staging_structure")
    def test_viewer_never_uses_database(self, schema):
        self.assertEqual(
            bulk.import_new_masters(
                CI_URL, role="VIEWER", actor="ci-viewer",
                domain="Müşteriler", rows=[{"name": "Dummy"}],
                confirmation=bulk.APPROVAL, backup_confirmed=True,
            ),
            ("forbidden", 0),
        )
        schema.assert_not_called()

    @patch.object(bulk, "validate_staging_structure")
    def test_revalidates_raw_rows_at_commit(self, schema):
        self.assertEqual(
            bulk.import_new_masters(
                CI_URL, role="ADMIN", actor="ci-admin",
                domain="Müşteriler", rows=[{"name": "", "unexpected": "SQL"}],
                confirmation=bulk.APPROVAL, backup_confirmed=True,
            )[0],
            "invalid_columns",
        )
        schema.assert_not_called()

    @patch.object(bulk, "validate_staging_structure", return_value=("mismatch", []))
    def test_schema_error_blocks_commit(self, schema):
        self.assertEqual(
            bulk.import_new_masters(
                CI_URL, role="ADMIN", actor="ci-admin",
                domain="Müşteriler", rows=[{"name": "Dummy"}],
                confirmation=bulk.APPROVAL, backup_confirmed=True,
            ),
            ("schema_mismatch", 0),
        )


if __name__ == "__main__":
    unittest.main()
