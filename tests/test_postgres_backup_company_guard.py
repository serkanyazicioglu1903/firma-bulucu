"""Old ct_app 26-table ZIP must not silently omit multi-company registries."""
import unittest
from unittest.mock import patch

from scripts import postgres_backup as backup

CI_URL = "postgresql://ci-review:fictional-ci-password@localhost:5432/db"


class CompanyBackupGuardTests(unittest.TestCase):
    @patch.object(backup, "validate_staging_structure", return_value=("ok", []))
    @patch.object(backup, "company_schema_status_on_cursor")
    @patch("psycopg.connect")
    def test_owner_migration_disables_both_legacy_zip_and_aes_source(
        self, connect, meta, structure,
    ):
        cur = connect.return_value.__enter__.return_value.cursor.return_value.__enter__.return_value
        for status in ("partial_company_schema", "company_schema_present",
                       "metadata_unavailable"):
            with self.subTest(status=status):
                cur.reset_mock()
                meta.return_value = status
                result, payload = backup.export_postgres_backup(CI_URL)
                self.assertEqual(result, "company_scope_unsupported")
                self.assertIsNone(payload)
                self.assertEqual(cur.execute.call_count, 3)
                executed = [c.args[0] for c in cur.execute.call_args_list]
                self.assertTrue(all(x.startswith("SET ") for x in executed))
                meta.assert_called_with(cur)

    @patch("psycopg.connect")
    def test_non_postgres_url_does_not_even_check_schema(self, connect):
        self.assertEqual(backup.export_postgres_backup("sqlite://demo"), (
            "invalid_url", None,
        ))
        connect.assert_not_called()


if __name__ == "__main__":
    unittest.main()
