"""Fail-closed tests for creating an isolated production-intended schema.

All database connections in these tests are mocked. They cannot touch Supabase.
"""
import unittest
from unittest.mock import MagicMock, patch

from scripts import postgres_live_schema as live


class LiveSchemaSafetyTests(unittest.TestCase):
    def test_ddl_plan_has_all_26_tables_and_never_uses_staging(self):
        tables, statements, fks = live.schema_ddl_steps()
        self.assertEqual((len(tables), len(statements)), (26, 26))
        self.assertEqual(len(set(tables)), 26)
        self.assertTrue(all(s.startswith("CREATE TABLE ") for s in statements))
        self.assertTrue(all(s.startswith("ALTER TABLE ") for s in fks))
        self.assertNotIn("ct_staging", "".join(statements + fks))

    def test_no_permission_never_provisions(self):
        with patch.object(live, "schema_ddl_steps") as ddl:
            self.assertEqual(live.provision_live_schema("postgresql://x@db/y"), "confirmation_required")
            ddl.assert_not_called()

    def test_invalid_url_prevents_provision(self):
        with patch.object(live, "schema_ddl_steps") as ddl:
            self.assertEqual(
                live.provision_live_schema("sqlite:///local.db", live.EXPLICIT_CONFIRMATION),
                "invalid_url",
            )
            ddl.assert_not_called()

    def _connection(self, exists):
        conn = MagicMock()
        cur = conn.transaction.return_value.__enter__.return_value
        cursor = conn.cursor.return_value.__enter__.return_value
        cursor.fetchone.return_value = (exists,)
        return conn, cursor

    @patch.object(live, "schema_ddl_steps", return_value=(
        ["customers"], ['CREATE TABLE "customers" ("id" BIGINT PRIMARY KEY);'], []
    ))
    @patch.object(live, "validate_staging_structure", return_value=("ok", []))
    @patch("psycopg.connect")
    def test_creates_only_new_schema_in_transaction(self, connect, validation, _ddl):
        conn, cur = self._connection(False)
        connect.return_value.__enter__.return_value = conn
        result = live.provision_live_schema(
            "postgresql://account:private@server/db", live.EXPLICIT_CONFIRMATION
        )
        self.assertEqual(result, "created")
        executed = [c.args[0] for c in cur.execute.call_args_list]
        self.assertIn('CREATE SCHEMA "ct_app"', executed)
        self.assertIn('SET LOCAL search_path TO "ct_app", pg_catalog', executed)
        self.assertIn('CREATE TABLE "customers" ("id" BIGINT PRIMARY KEY);', executed)
        self.assertTrue(all("DROP " not in statement for statement in executed))
        validation.assert_called_once_with(
            "postgresql://account:private@server/db", schema="ct_app"
        )

    @patch.object(live, "schema_ddl_steps", return_value=(
        ["customers"], ['CREATE TABLE "customers" (id BIGINT);'], []
    ))
    @patch("psycopg.connect")
    def test_existing_schema_refuses_all_ddl(self, connect, _ddl):
        conn, cur = self._connection(True)
        connect.return_value.__enter__.return_value = conn
        self.assertEqual(
            live.provision_live_schema(
                "postgresql://account:private@server/db", live.EXPLICIT_CONFIRMATION
            ), "exists"
        )
        executed = [c.args[0] for c in cur.execute.call_args_list]
        self.assertFalse(any(s.startswith("CREATE") for s in executed))

    @patch.object(live, "schema_ddl_steps", return_value=(
        ["customers"], ['CREATE TABLE "customers" (id BIGINT);'], []
    ))
    @patch("psycopg.connect", side_effect=RuntimeError("password private-secret"))
    def test_provision_error_never_leaks_credentials(self, _connect, _ddl):
        status = live.provision_live_schema(
            "postgresql://private-secret@server/db", live.EXPLICIT_CONFIRMATION
        )
        self.assertEqual(status, "failed")
        self.assertNotIn("secret", status)

    @patch("psycopg.connect")
    def test_read_only_schema_status_checks_catalog(self, connect):
        conn, cur = self._connection(False)
        connect.return_value.__enter__.return_value = conn
        self.assertEqual(
            live.read_live_schema_status("postgresql://user:secret@server/db"),
            "not_created",
        )
        executed = [c.args[0] for c in cur.execute.call_args_list]
        self.assertEqual(executed[0], "SET TRANSACTION READ ONLY")
        self.assertFalse(any(s.startswith("CREATE") for s in executed))


if __name__ == "__main__":
    unittest.main()
