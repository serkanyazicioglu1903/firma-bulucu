"""No production migrations, account assignments or company backfills."""
from pathlib import Path
import unittest
from unittest.mock import MagicMock

from scripts.four_company_foundation_ddl import (
    foundation_ddl, foundation_status_on_cursor, private_company_tables,
)
from scripts.postgres_company_full_coverage import _catalog_tables


class CompanyFoundationPlanTests(unittest.TestCase):
    def test_23_private_tables_and_3_special_policies(self):
        private = private_company_tables()
        self.assertEqual(len(private), 23)
        self.assertEqual(len(_catalog_tables()), 26)
        self.assertEqual(set(_catalog_tables()) - set(private), {
            "product_catalog", "audit_log", "system_settings"
        })

    def test_no_company_identity_seed_and_no_assumed_owner(self):
        statements = foundation_ddl()
        self.assertEqual(len(statements), 5 + 23 * 2)
        assert statements[0].startswith('CREATE TABLE "ct_app"."legal_entities"')
        self.assertIn("can_read BOOLEAN NOT NULL DEFAULT FALSE",
                      statements[1])
        self.assertIn("can_write BOOLEAN NOT NULL DEFAULT FALSE",
                      statements[2])
        assert all('NULL REFERENCES "ct_app"."legal_entities"(id)' in x
                   for x in statements if x.startswith("ALTER TABLE"))
        assert sum(x.startswith("ALTER TABLE") for x in statements) == 23
        assert sum(x.startswith("CREATE INDEX") for x in statements) == 23
        for statement in statements:
            for forbidden in (
                "INSERT INTO", "UPDATE ", "DELETE FROM", "DROP TABLE",
                "GRANT ", "CREATE POLICY", "ENABLE ROW LEVEL SECURITY",
                "SET DEFAULT", "TRUNCATE",
            ):
                self.assertNotIn(forbidden, statement)
        self.assertFalse(any("AS_ILERI_GIDA" in s for s in statements))
        self.assertFalse(any("ci-scoped-reader" in s for s in statements))

    def test_legacy_metadata_only_allows_isolated_rehearsal(self):
        cursor = MagicMock()
        expected = sorted(_catalog_tables())
        cursor.fetchall.side_effect = [
            [(name, False, False, False, False) for name in expected], []
        ]
        self.assertEqual(
            foundation_status_on_cursor(cursor),
            "legacy_ready_for_isolated_rehearsal",
        )
        self.assertEqual(cursor.execute.call_count, 2)
        assert all(x.args[0].startswith("SELECT ")
                   for x in cursor.execute.call_args_list)

    def test_partial_migration_and_existing_registry_fail_closed(self):
        expected = sorted(_catalog_tables())
        for check in range(1, 5):
            with self.subTest(check=check):
                rows = [[name, False, False, False, False]
                        for name in expected]
                rows[0][check] = True
                cursor = MagicMock()
                cursor.fetchall.return_value = list(map(tuple, rows))
                self.assertEqual(
                    foundation_status_on_cursor(cursor),
                    "already_migrating",
                )
                self.assertEqual(cursor.execute.call_count, 1)
        cursor = MagicMock()
        cursor.fetchall.side_effect = [
            [(name, False, False, False, False) for name in expected],
            [("company_read_grants",)],
        ]
        self.assertEqual(
            foundation_status_on_cursor(cursor),
            "already_migrating",
        )

    def test_missing_inventory_never_proceeds(self):
        cursor = MagicMock()
        cursor.fetchall.return_value = [
            (name, False, False, False, False)
            for name in sorted(_catalog_tables())[:-1]
        ]
        self.assertEqual(
            foundation_status_on_cursor(cursor), "schema_mismatch"
        )

    def test_offline_module_has_no_database_connector_or_entrypoint(self):
        source = (Path(__file__).resolve().parents[1] / "scripts" /
                  "four_company_foundation_ddl.py").read_text()
        for forbidden in (
            "import psycopg", "psycopg.connect", "os.environ",
            "st.session_state", "APP_USERS_JSON", "commit()",
            "INSERT INTO", "CREATE ROLE",
        ):
            self.assertNotIn(forbidden, source)


if __name__ == "__main__":
    unittest.main()
