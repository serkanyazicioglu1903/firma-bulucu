"""Pure metadata/role permission tests: never contact the live Supabase DB."""
import unittest
from unittest.mock import MagicMock, patch

from scripts import postgres_tenant_security_preflight as p

NAMES = sorted(p.schema_ddl_steps()[0])


def rows_with(rls=False, table=None, actor="anon", can_write=False):
    result = []
    indexes = {"anon": (3, 4), "authenticated": (5, 6),
               "service_role": (7, 8)}
    for name in NAMES:
        row = [name, rls, False, False, False, False, False, False, False]
        if name == table:
            row[indexes[actor][0]] = True
            row[indexes[actor][1]] = can_write
        result.append(tuple(row))
    return result


class TenantSecurityPreflightTests(unittest.TestCase):
    def test_rls_off_without_api_grant_does_not_claim_public_exposure(self):
        report = p.summarize_access_catalog(
            rows_with(), 0, (False,) * 5, 0,
            (False, False, False),
        )
        self.assertEqual(report["status"], "tenant_migration_incomplete")
        self.assertEqual(report["total_tables"], 26)
        self.assertEqual(report["rls_enabled"], 0)
        self.assertEqual(report["owner_columns"], 0)
        self.assertEqual(report["api_direct_access"]["anon"], 0)
        self.assertEqual(report["api_direct_access"]["authenticated"], 0)
        self.assertFalse(report["company_isolation_verified"])
        self.assertFalse(report["ready_for_production_cutover"])
        self.assertFalse(report["actual_backup_restore_verified"])

    def test_single_api_grant_is_visible_but_never_approves_rls(self):
        for role in p.ACTORS:
            with self.subTest(role=role):
                report = p.summarize_access_catalog(
                    rows_with(table="cash_accounts", actor=role, can_write=True),
                    0, (False,) * 5, 0, (False, False, False),
                )
                self.assertEqual(report["status"], "api_permissions_review")
                self.assertEqual(report["api_direct_access"][role], 1)
                self.assertEqual(report["api_direct_writes"][role], 1)
                self.assertFalse(report["ready_for_production_cutover"])

    def test_all_rls_and_owner_tables_still_do_not_prove_restore(self):
        report = p.summarize_access_catalog(
            rows_with(rls=True), 8, (True,) * 5, 26,
            (False, False, False),
        )
        self.assertEqual(report["status"], "review_required")
        self.assertEqual(report["registry_tables"], 5)
        self.assertEqual(report["rls_enabled"], 26)
        self.assertFalse(report["company_isolation_verified"])
        self.assertFalse(report["actual_backup_restore_verified"])
        self.assertFalse(report["ready_for_production_cutover"])

    def test_partial_and_invalid_metadata_fails_closed(self):
        bad_inputs = [
            rows_with()[:-1],
            rows_with() + [rows_with()[0]],
            [(*rows_with()[0][:1], "false", *rows_with()[0][2:])]
            + rows_with()[1:],
            [("not_a_real_table", *rows_with()[0][1:])]
            + rows_with()[1:],
        ]
        for values in bad_inputs:
            with self.subTest(values_len=len(values)):
                result = p.summarize_access_catalog(
                    values, 0, (False,) * 5, 0, (False,) * 3
                )
                self.assertEqual(result["status"], "failed")
                self.assertFalse(result["ready_for_production_cutover"])
        self.assertEqual(p.summarize_access_catalog(
            rows_with(), 8, (True,) * 4, 0, (False,) * 3,
        )["status"], "failed")

    def test_elevated_server_role_is_not_tenant_validation(self):
        report = p.summarize_access_catalog(
            rows_with(), 0, (False,) * 5, 0, (True, True, False),
        )
        self.assertTrue(report["current_session_elevated"])
        self.assertFalse(report["company_isolation_verified"])

    def test_read_only_schema_catalog_never_fetches_business_rows(self):
        cur = MagicMock()
        cur.fetchall.return_value = rows_with()
        cur.fetchone.side_effect = [
            (0,), (False,) * 5, (0,), (False, False, False),
        ]
        result = p.inspect_access_catalog_on_cursor(cur)
        self.assertEqual(result["status"], "tenant_migration_incomplete")
        self.assertEqual(cur.execute.call_count, 5)
        statements = [call.args[0] for call in cur.execute.call_args_list]
        self.assertTrue(all(stmt.startswith("SELECT ") for stmt in statements))
        self.assertTrue(all("pg_" in stmt or "to_regclass" in stmt for stmt in statements))
        self.assertTrue(all("SELECT * FROM" not in stmt for stmt in statements))
        self.assertTrue(all(
            not stmt.lstrip().startswith(("INSERT", "UPDATE", "DELETE", "DROP", "ALTER"))
            for stmt in statements
        ))

    @patch("psycopg.connect")
    def test_invalid_target_never_connects(self, connect):
        report = p.inspect_company_access_security("sqlite://untrusted")
        self.assertEqual(report["status"], "invalid_url")
        connect.assert_not_called()


if __name__ == "__main__":
    unittest.main()
