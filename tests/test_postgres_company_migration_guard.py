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
