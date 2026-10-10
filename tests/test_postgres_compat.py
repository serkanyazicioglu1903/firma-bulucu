"""PostgreSQL compatibility bridge: placeholders, dates, aggregates and roles."""
import unittest
from unittest.mock import MagicMock, patch

from scripts.postgres_compat import (
    CompatConnection, CompatRow, pg_execute, translate_sql,
)


class SqlTranslationTests(unittest.TestCase):
    def test_question_marks_outside_literals(self):
        self.assertEqual(
            translate_sql("SELECT '?' AS literal, a FROM x WHERE id=? AND name=?"),
            "SELECT '?' AS literal, a FROM x WHERE id=%s AND name=%s",
        )

    def test_percent_escaped_for_psycopg(self):
        self.assertEqual(
            translate_sql("SELECT * FROM x WHERE code LIKE '%A%' AND id=?"),
            "SELECT * FROM x WHERE code LIKE '%%A%%' AND id=%s",
        )

    def test_scalar_min_max_but_not_aggregates(self):
        q = translate_sql(
            "SELECT MIN(quality_hold_kg,quantity_available_kg),"
            "MAX(value,0),MAX(t.amount),MAX(CASE WHEN ok THEN 1 ELSE 0 END)"
        )
        self.assertIn("LEAST(quality_hold_kg,quantity_available_kg)", q)
        self.assertIn("GREATEST(value,0)", q)
        self.assertIn("MAX(t.amount)", q)
        self.assertIn("MAX(CASE", q)

    def test_postgres_retains_legacy_uppercase_ui_aliases(self):
        sql = translate_sql("SELECT po.po_number AS PO, expiry_date AS SKT FROM shipments")
        self.assertIn('AS "PO"', sql)
        self.assertIn('AS "SKT"', sql)

    def test_round_two_argument_double_precision_sql(self):
        translated = translate_sql(
            "SELECT ROUND(SUM(value*probability/100.0),0),ROUND(value),"
            "ROUND(CASE WHEN value>0 THEN value ELSE 0 END,2) FROM x"
        )
        self.assertIn("(ROUND(CAST(SUM(value*probability/100.0) AS NUMERIC), 0))::double precision", translated)
        self.assertIn("ROUND(value)", translated)
        self.assertIn("(ROUND(CAST(CASE WHEN value>0 THEN value ELSE 0 END AS NUMERIC), 2))::double precision", translated)

    def test_julianday_nested_and_now(self):
        sql = translate_sql(
            "SELECT CAST(julianday(date('now'))-julianday(NULLIF(o.due_date,'')) "
            "AS INTEGER) FROM x WHERE o.id=?"
        )
        self.assertIn("EXTRACT(EPOCH FROM CURRENT_DATE::timestamp)", sql)
        self.assertIn("NULLIF(CAST(NULLIF(o.due_date,'') AS TEXT),'')::date", sql)
        self.assertTrue(sql.endswith("o.id=%s"))
        self.assertNotIn("julianday(", sql)

    def test_julianday_aggregate_argument(self):
        sql = translate_sql("SELECT julianday(MAX(a.activity_date)) FROM activities a")
        self.assertIn("CAST(MAX(a.activity_date) AS TEXT)", sql)
        self.assertNotIn("julianday(", sql)

    def test_iso_date_strings_stay_text_comparable(self):
        sql = translate_sql("SELECT * FROM tasks WHERE due_date<date('now')")
        self.assertIn("due_date<CURRENT_DATE::text", sql)

    def test_compat_row_supports_sqlite_style_column_and_index(self):
        row = CompatRow(("id", "name"), (15, "TEST"))
        self.assertEqual(row[0], 15)
        self.assertEqual(row["name"], "TEST")
        self.assertEqual(row.keys(), ["id", "name"])

    @patch("scripts.postgres_compat._pool")
    @patch("security_admin.current_user", return_value={"role": "VIEWER", "username": "test"})
    def test_direct_write_rejected_without_scope(self, _user, pool):
        conn = MagicMock()
        pool.return_value.connection.return_value.__enter__.return_value = conn
        with CompatConnection("postgresql://test/db") as c:
            with self.assertRaises(PermissionError):
                c.execute("INSERT INTO customers(name) VALUES (?)", ("No",))
        queries = [call.args[0] for call in conn.execute.call_args_list]
        self.assertFalse(any(q.startswith("INSERT") for q in queries))

    @patch("scripts.postgres_compat._pool")
    def test_pg_execute_fails_closed_without_live_scope(self, pool):
        with self.assertRaises(PermissionError):
            pg_execute("postgresql://test/db",
                       "INSERT INTO customers(name) VALUES (?)",
                       ("No",), actor="ci", role="ADMIN")
        pool.assert_not_called()


if __name__ == "__main__":
    unittest.main()
