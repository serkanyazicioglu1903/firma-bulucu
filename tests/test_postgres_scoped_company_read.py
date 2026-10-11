"""Offline tests: untrusted company IDs and DB reads fail closed."""
import unittest
from unittest.mock import MagicMock, patch

from scripts.group_company_catalog import COMPANY_LABELS
from scripts.postgres_company_scope import CRITICAL_TABLES
from scripts.postgres_scoped_company_read import (
    LIMIT, OWNED_READ_SECTIONS, grant_table_rehearsal_ddl,
    read_company_records, read_company_records_on_cursor,
)


class ScopedCompanyReadTests(unittest.TestCase):
    def test_every_critical_finance_operation_has_fixed_company_scoped_query(self):
        self.assertEqual(
            {table for table, _ in OWNED_READ_SECTIONS.values()},
            set(CRITICAL_TABLES),
        )
        self.assertEqual(LIMIT, 100)
        self.assertEqual(len(grant_table_rehearsal_ddl()), 1)
        self.assertIn("can_read BOOLEAN NOT NULL DEFAULT FALSE",
                      grant_table_rehearsal_ddl()[0])
        self.assertNotIn("INSERT ", grant_table_rehearsal_ddl()[0])
        self.assertNotIn("GRANT ", grant_table_rehearsal_ddl()[0])

    @patch("psycopg.connect")
    def test_invalid_company_principal_or_section_cannot_connect(self, connect):
        invalid = (
            ("", "AS_ILERI_GIDA", "Stok"),
            ("' OR TRUE --", "AS_ILERI_GIDA", "Stok"),
            ("user", "MISSING", "Stok"),
            ("user", "AS_ILERI_GIDA", "SELECT * FROM cash_accounts"),
            ("user", "AS_ILERI_GIDA", "Müşteriler"),
        )
        for person, company, section in invalid:
            with self.subTest(company=company,section=section):
                self.assertEqual(
                    read_company_records(
                        "postgresql://fake-user:fake-pass@host/db",
                        person, company, section,
                    ), ("forbidden", []),
                )
        connect.assert_not_called()

    def test_missing_owner_columns_are_blocked_before_grants(self):
        cur = MagicMock()
        cur.fetchone.return_value = (0,)
        self.assertEqual(
            read_company_records_on_cursor(
                cur, "ci-user", "AS_ILERI_GIDA", "Banka / Kasa"
            ), ("not_ready", []),
        )
        self.assertEqual(cur.execute.call_count, 1)

    def test_missing_grant_registry_is_not_ready(self):
        cur = MagicMock()
        cur.fetchone.side_effect = [(8,), (True, False)]
        self.assertEqual(
            read_company_records_on_cursor(
                cur, "ci-user", "AS_ILERI_GIDA", "Banka / Kasa"
            ), ("not_ready", []),
        )
        self.assertEqual(cur.execute.call_count, 2)

    def test_unknown_or_revoked_grant_denied_without_fetching_rows(self):
        cur = MagicMock()
        cur.fetchone.side_effect = [(8,), (True, True), None]
        self.assertEqual(
            read_company_records_on_cursor(
                cur, "ci-user", "AS_ILERI_HOLDING", "Finans Hareketleri"
            ), ("forbidden", []),
        )
        self.assertEqual(cur.execute.call_count, 3)
        cur.fetchall.assert_not_called()

    def test_authorized_bank_query_is_bounded_and_still_joins_db_grant(self):
        cur = MagicMock()
        cur.fetchone.side_effect = [(8,), (True, True), (42,)]
        cur.fetchall.return_value = [(51, "CI BANK", "GBP", 12, 1)]
        result, rows = read_company_records_on_cursor(
            cur, "ci-user", "AS_FOOD_GLOBAL", "Banka / Kasa"
        )
        self.assertEqual(result, "ok")
        self.assertEqual(rows, [
            {"id": 51, "name": "CI BANK", "currency": "GBP",
             "balance": 12, "active": 1},
        ])
        sql, params = cur.execute.call_args.args
        self.assertIn('"ct_app"."cash_accounts"', sql)
        self.assertIn("b.legal_entity_id", sql)
        self.assertIn('"ct_app"."company_read_grants"', sql)
        self.assertIn("g.principal_id=%s AND g.can_read=TRUE", sql)
        self.assertIn("LIMIT 100", sql)
        self.assertNotIn("ci-user", sql)
        self.assertNotIn("AS_FOOD_GLOBAL", sql)
        self.assertEqual(params, (42, "AS_FOOD_GLOBAL", "ci-user"))

    def test_no_implicit_holding_or_admin_access(self):
        self.assertEqual(len(COMPANY_LABELS), 4)
        cur = MagicMock()
        cur.fetchone.side_effect = [(8,), (True, True), None]
        self.assertEqual(
            read_company_records_on_cursor(
                cur, "admin", "AS_ILERI_HOLDING", "Banka / Kasa"
            ), ("forbidden", []),
        )


if __name__ == "__main__":
    unittest.main()
