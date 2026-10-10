"""Read-only and authorization regression tests for PostgreSQL 360 UI."""
import unittest
from unittest.mock import MagicMock, patch

from scripts import postgres_operational_read as pg

URL = "postgresql://user:never-display-password@localhost/db"


class PostgresOperationalWorkspaceTests(unittest.TestCase):
    def test_no_arbitrary_sql_or_unknown_sections(self):
        with patch.object(pg, "validate_staging_structure") as schema:
            self.assertEqual(pg.read_operational_workspace(URL, "DROP TABLE customers"),
                             ("invalid_workspace", []))
            schema.assert_not_called()

    def test_invalid_url_fails_without_schema_or_connection(self):
        with patch.object(pg, "validate_staging_structure") as schema:
            self.assertEqual(pg.read_operational_workspace(
                "sqlite:///db", "Müşteriler"
            ), ("invalid_url", []))
            schema.assert_not_called()

    @patch.object(pg, "validate_staging_structure", return_value=("mismatch", []))
    @patch("psycopg.connect")
    def test_invalid_schema_blocks_all_reads(self, connect, schema):
        self.assertEqual(
            pg.read_operational_workspace(URL, "Müşteriler"),
            ("schema_mismatch", []),
        )
        connect.assert_not_called()
        schema.assert_called_once_with(URL, schema="ct_app")

    @patch.object(pg, "validate_staging_structure", return_value=("ok", []))
    @patch("psycopg.connect")
    def test_each_section_is_explicit_and_limited(self, connect, schema):
        cur = MagicMock()
        cur.fetchall.return_value = [
            {"id": 1, "name": "FICTIONAL ONLY"},
        ]
        connect.return_value.__enter__.return_value.cursor.return_value.__enter__.return_value = cur
        self.assertEqual(len(pg.WORKSPACE_QUERIES), 10)
        for label, query in pg.WORKSPACE_QUERIES.items():
            with self.subTest(label=label):
                self.assertIn('FROM "ct_app"."', query)
                self.assertIn("LIMIT 100", query)
                self.assertNotIn("SELECT *", query)
                status, rows = pg.read_operational_workspace(URL, label)
                self.assertEqual(status, "ok")
                self.assertEqual(rows, [{"id": 1, "name": "FICTIONAL ONLY"}])
                schema.assert_called_with(URL, schema="ct_app")
                executed = [c.args[0] for c in cur.execute.call_args_list[-4:]]
                self.assertEqual(executed[0], "SET TRANSACTION READ ONLY")
                self.assertEqual(executed[-1], query)
                self.assertFalse(any(
                    sql.strip().startswith(("INSERT", "UPDATE", "DELETE", "DROP"))
                    for sql in executed
                ))

    @patch.object(pg, "validate_staging_structure", return_value=("ok", []))
    @patch("psycopg.connect", side_effect=RuntimeError("password never-display-password"))
    def test_connection_error_does_not_reveal_secrets(self, *_):
        result = pg.read_operational_workspace(URL, "Finans Hareketleri")
        self.assertEqual(result, ("failed", []))
        self.assertNotIn("never-display-password", str(result))


if __name__ == "__main__":
    unittest.main()
