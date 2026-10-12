"""No live RLS change: policies are only SQL returned for CI test rollback."""
from pathlib import Path
import unittest

from scripts.four_company_rls_ci_proof import CI_ROLES, ci_23_table_rls_sql
from scripts.four_company_foundation_ddl import private_company_tables


class Ci23TableRlsPlanTests(unittest.TestCase):
    def test_fixed_23_table_coverage(self):
        statements = ci_23_table_rls_sql()
        self.assertEqual(len(CI_ROLES), 4)
        self.assertEqual(len(statements), 6 + 5 * 23)
        self.assertEqual(
            sum(x.startswith("CREATE ROLE ") for x in statements), 4
        )
        self.assertEqual(
            sum(x.startswith("CREATE POLICY ci_23_company_read ")
                for x in statements), 23
        )
        self.assertEqual(
            sum(x.startswith("CREATE POLICY ci_23_company_insert ")
                for x in statements), 23
        )
        for table in private_company_tables():
            self.assertEqual(
                sum('ENABLE ROW LEVEL SECURITY' in x
                    and f'"ct_app"."{table}"' in x
                    for x in statements), 1
            )
            self.assertEqual(
                sum('FORCE ROW LEVEL SECURITY' in x
                    and f'"ct_app"."{table}"' in x
                    for x in statements), 1
            )
            self.assertEqual(
                sum(x.startswith("CREATE POLICY ci_23_company_read ")
                    and f'ON "ct_app"."{table}" ' in x
                    and f'"{table}".legal_entity_id' in x
                    for x in statements), 1
            )
            self.assertEqual(
                sum(x.startswith("CREATE POLICY ci_23_company_insert ")
                    and f'ON "ct_app"."{table}" ' in x
                    and f'"{table}".legal_entity_id' in x
                    for x in statements), 1
            )

    def test_no_wildcard_privileges_for_real_accounts_or_api_roles(self):
        code = "\n".join(ci_23_table_rls_sql())
        self.assertIn("AND g.can_read=TRUE", code)
        self.assertIn("AND g.can_write=TRUE", code)
        self.assertIn("CURRENT_USER", code)
        self.assertIn("NOBYPASSRLS", code)
        self.assertNotIn("TO PUBLIC", code)
        self.assertNotIn("TO anon", code)
        self.assertNotIn("TO authenticated", code)
        self.assertNotIn("TO service_role", code)
        self.assertNotIn("SUPERUSER", code.replace("NOSUPERUSER", ""))
        self.assertNotIn("product_catalog", code)
        self.assertNotIn('"ct_app"."audit_log"', code)
        self.assertNotIn('"ct_app"."system_settings"', code)
        self.assertNotIn("INSERT INTO", code)
        self.assertNotIn("UPDATE ", code)
        self.assertNotIn("DELETE FROM", code)
        self.assertNotIn("DROP ", code)
        self.assertNotIn("CREATE ROLE postgres", code)

    def test_no_connector_and_no_production_runner(self):
        source = (Path(__file__).resolve().parents[1] / "scripts" /
                  "four_company_rls_ci_proof.py").read_text()
        for unsafe in ("import psycopg", "psycopg.connect", "os.environ",
                       "SUPABASE", "commit()", "streamlit", "APP_USERS_JSON"):
            self.assertNotIn(unsafe, source)


if __name__ == "__main__":
    unittest.main()
