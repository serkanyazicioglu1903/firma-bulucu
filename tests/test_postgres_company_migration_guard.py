"""Automatic read-only guard for the previous unscoped business screens."""
import unittest
from unittest.mock import MagicMock, patch

import control_tower as ct
from scripts import postgres_company_migration_guard as guard

TABLES = tuple(guard.ALLOWED_TABLES)


class CompanyMigrationGuardTests(unittest.TestCase):
    def test_existing_legacy_schema_keeps_current_path(self):
        self.assertEqual(
            guard.classify_schema_metadata(TABLES, (), (False, False, False, False, False)),
            "legacy_schema_only",
        )

    def test_any_migration_marker_or_owner_column_blocks_legacy(self):
        for owner_rows, markers in (
            ((), (True, False, False, False, False)),
            ((), (False, True, False, False, False)),
            ((), (False, False, True, False, False)),
            ((), (False, False, False, True, False)),
            ((), (False, False, False, False, True)),
            (("purchase_orders",), (True, False, False, False, False)),
            (TABLES[:-1], (True, True, True, True, True)),
            (TABLES, (False, False, False, False, False)),
            (TABLES, (True, True, False, False, False)),
        ):
            with self.subTest(owner=owner_rows, markers=markers):
                self.assertEqual(
                    guard.classify_schema_metadata(TABLES, owner_rows, markers),
                    "partial_company_schema",
                )
        self.assertEqual(
            guard.classify_schema_metadata(TABLES, TABLES, (True, True, True, True, True)),
            "company_schema_present",
        )

    def test_unexpected_or_incomplete_metadata_denied(self):
        bad = [
            (TABLES[:-1], (), (False, False, False, False, False)),
            (TABLES, ("unknown_table",), (False, False, False, False, False)),
            (TABLES, ("payables", "payables"), (True, False, False, False, False)),
            (TABLES, (), ("false", False, False, False, False)),
            (TABLES, (), None),
            (TABLES, (), (False, False)),
            (TABLES, (), (True, 1, False, False, False)),
        ]
        for tables, cols, markers in bad:
            with self.subTest(tables=tables, cols=cols):
                self.assertEqual(
                    guard.classify_schema_metadata(tables, cols, markers),
                    "metadata_unavailable",
                )

    def test_fixed_pg_catalog_queries_never_read_data_or_write(self):
        cur = MagicMock()
        cur.fetchall.side_effect = [
            [(value,) for value in TABLES], [("payables",)],
        ]
        cur.fetchone.return_value = (True, False, False, False, False)
        self.assertEqual(
            guard.company_schema_status_on_cursor(cur),
            "partial_company_schema",
        )
        self.assertEqual(cur.execute.call_count, 3)
        for call in cur.execute.call_args_list:
            sql = call.args[0]
            self.assertTrue(sql.startswith("SELECT "))
            self.assertNotIn("INSERT ", sql)
            self.assertNotIn("UPDATE ", sql)
            self.assertNotIn("DELETE ", sql)
            self.assertNotIn("SELECT *", sql)

    def _extended_rows(self, modified=None):
        flags = modified or {}
        return [
            (name,) + tuple(flags.get(name, (False,) * 5))
            for name in sorted(guard.EXPECTED_TABLES)
        ]

    def test_clean_26_table_metadata_preserves_existing_legacy_route(self):
        cur = MagicMock()
        cur.fetchall.side_effect = [
            [(name,) for name in TABLES],
            [],
            self._extended_rows(),
        ]
        cur.fetchone.return_value = (False, False, False, False, False)
        self.assertEqual(
            guard.company_schema_status_on_cursor(cur), "legacy_schema_only"
        )
        self.assertEqual(cur.execute.call_count, 4)
        statements = [call.args[0] for call in cur.execute.call_args_list]
        self.assertTrue(all(sql.startswith("SELECT ") for sql in statements))
        self.assertIn("pg_roles", statements[-1])
        self.assertIn("pg_policy", statements[-1])
        self.assertNotIn("FROM ct_app.", " ".join(statements))

    def test_any_noncritical_owner_rls_policy_or_api_grant_blocks_legacy(self):
        self.assertIn("customers", guard.EXPECTED_TABLES - guard.ALLOWED_TABLES)
        for index, name in enumerate((
            "owner_column", "rls", "force_rls", "policy", "api_grant"
        )):
            with self.subTest(signal=name):
                signal = [False] * 5
                signal[index] = True
                cur = MagicMock()
                cur.fetchall.side_effect = [
                    [(table,) for table in TABLES], [],
                    self._extended_rows({"customers": tuple(signal)}),
                ]
                cur.fetchone.return_value = (
                    False, False, False, False, False
                )
                self.assertEqual(
                    guard.company_schema_status_on_cursor(cur),
                    "partial_company_schema",
                )

    def test_untrusted_or_incomplete_extended_metadata_fails_closed(self):
        correct = self._extended_rows()
        for bad in (
            correct[:-1],
            correct + [correct[-1]],
            correct[:-1] + [("unknown",) + (False,) * 5],
            correct[:-1] + [(correct[-1][0], "false") + (False,) * 4],
            correct[:-1] + [("customers",) + (False,) * 5],
            None,
        ):
            with self.subTest(case=str(bad)[-45:]):
                status = guard.classify_extended_migration_signals(bad)
                self.assertIsNone(status)
                cur = MagicMock()
                cur.fetchall.side_effect = [
                    [(table,) for table in TABLES], [], bad,
                ]
                cur.fetchone.return_value = (
                    False, False, False, False, False
                )
                self.assertEqual(
                    guard.company_schema_status_on_cursor(cur),
                    "metadata_unavailable",
                )

    @patch("psycopg.connect")
    def test_invalid_url_never_connects(self, connect):
        self.assertEqual(
            guard.inspect_company_migration_state("sqlite:///not-a-db"),
            "metadata_unavailable",
        )
        connect.assert_not_called()

    @patch.object(ct, "st")
    @patch.object(ct, "inspect_company_migration_state",
                  return_value="partial_company_schema")
    @patch.object(ct, "scoped_company_view_enabled", return_value=False)
    @patch.object(ct, "postgres_url", return_value="ci-db")
    @patch.object(ct, "login_gate", return_value=True)
    @patch.object(ct, "render_role_portal")
    @patch.object(ct, "render_postgres_workspace")
    def test_partial_migration_never_renders_legacy_finance_or_import(
        self, workspace, role_portal, _login, _url, _mode,
        inspect, st,
    ):
        ct._render_control_tower_interface(live_postgres=True)
        inspect.assert_called_once_with("ci-db")
        st.error.assert_called_once()
        st.tabs.assert_not_called()
        workspace.assert_not_called()
        role_portal.assert_not_called()

    @patch.object(ct, "st")
    @patch.object(ct, "inspect_company_migration_state",
                  return_value="metadata_unavailable")
    @patch.object(ct, "scoped_company_view_enabled", return_value=False)
    @patch.object(ct, "postgres_url", return_value="ci-db")
    @patch.object(ct, "login_gate", return_value=True)
    def test_metadata_error_fails_closed(self, _login, _url, _mode, inspect, st):
        ct._render_control_tower_interface(live_postgres=True)
        inspect.assert_called_once()
        st.error.assert_called_once()
        st.tabs.assert_not_called()

    @patch.object(ct, "st")
    @patch.object(ct, "render_scoped_company_workspace")
    @patch.object(ct, "inspect_company_migration_state")
    @patch.object(ct, "scoped_company_view_enabled", return_value=True)
    @patch.object(ct, "postgres_url", return_value="ci-db")
    @patch.object(ct, "login_gate", return_value=True)
    def test_signed_viewer_routing_is_exclusive_and_no_legacy_probe_needed(
        self, _login, _url, _mode, inspect, viewer, st,
    ):
        ct._render_control_tower_interface(live_postgres=True)
        viewer.assert_called_once_with("ci-db")
        inspect.assert_not_called()
        st.tabs.assert_not_called()


if __name__ == "__main__":
    unittest.main()
