"""Grant-scoped CRM is read-only and unavailable before actual ownership."""
import unittest
from unittest.mock import MagicMock, patch

from scripts import postgres_scoped_company_crm_read as crm


class CompanyCrmReadTests(unittest.TestCase):
    def test_only_customer_and_contact_sections_are_exposed(self):
        self.assertEqual(set(crm.CRM_READ_SECTIONS), {
            "Müşteriler", "İrtibat Kişileri",
        })
        self.assertEqual(crm.LIMIT, 100)

    @patch("psycopg.connect")
    def test_invalid_principal_company_and_tab_never_connect(self, connect):
        for person, code, section in (
            ("", "AS_ILERI_GIDA", "Müşteriler"),
            ("' OR 1=1 --", "AS_ILERI_GIDA", "Müşteriler"),
            ("ci-user", "*", "Müşteriler"),
            ("ci-user", "AS_ILERI_GIDA", "Banka / Kasa"),
            ("ci-user", "AS_ILERI_GIDA", "SELECT * FROM customers"),
        ):
            with self.subTest(person=person, company=code, section=section):
                self.assertEqual(
                    crm.read_company_crm(
                        "postgresql://unused:unused@host.example/postgres",
                        person, code, section,
                    ), ("forbidden", []),
                )
        connect.assert_not_called()

    def test_owner_fields_missing_returns_no_crm(self):
        cur = MagicMock()
        cur.fetchall.return_value = []
        with patch.object(crm, "authorize_company_on_cursor",
                          return_value=("ok", 24)):
            result = crm.read_company_crm_on_cursor(
                cur, "verified-principal", "AS_ILERI_GIDA", "Müşteriler"
            )
        self.assertEqual(result, ("not_ready", []))
        self.assertEqual(cur.execute.call_count, 1)
        self.assertTrue(
            cur.execute.call_args.args[0].startswith("SELECT ")
        )

    def test_grant_denial_happens_before_crm_catalog_and_rows(self):
        cur = MagicMock()
        with patch.object(crm, "authorize_company_on_cursor",
                          return_value=("forbidden", None)):
            result = crm.read_company_crm_on_cursor(
                cur, "ci-unauthorized", "AS_FOOD_GLOBAL", "İrtibat Kişileri"
            )
        self.assertEqual(result, ("forbidden", []))
        cur.execute.assert_not_called()
        cur.fetchall.assert_not_called()

    def test_missing_composite_fk_even_with_two_owners_is_not_ready(self):
        cur = MagicMock()
        cur.fetchall.return_value = [("customers",), ("contacts",)]
        cur.fetchone.return_value = (False,)
        with patch.object(crm, "authorize_company_on_cursor",
                          return_value=("ok", 24)):
            self.assertEqual(
                crm.read_company_crm_on_cursor(
                    cur, "ci-user", "AS_ILERI_GIDA", "İrtibat Kişileri"
                ), ("not_ready", []),
            )
        self.assertEqual(cur.execute.call_count, 2)
        cur.fetchall.assert_called_once()

    def test_granted_customer_query_always_filters_by_db_owner_and_grant(self):
        cur = MagicMock()
        cur.fetchall.side_effect = [
            [("customers",), ("contacts",)],
            [(5, "CI Factory", "UK", "Ingredient", "Potansiyel", "CI", "GBP")],
        ]
        cur.fetchone.return_value = (True,)
        with patch.object(crm, "authorize_company_on_cursor",
                          return_value=("ok", 42)):
            status, rows = crm.read_company_crm_on_cursor(
                cur, "ci-user", "AS_FOOD_GLOBAL", "Müşteriler"
            )
        self.assertEqual(status, "ok")
        self.assertEqual(rows[0]["name"], "CI Factory")
        self.assertEqual(rows[0]["currency"], "GBP")
        sql, params = cur.execute.call_args.args
        self.assertIn('"ct_app"."customers" b', sql)
        self.assertIn("b.legal_entity_id=%s", sql)
        self.assertIn("g.principal_id=%s AND g.can_read=TRUE", sql)
        self.assertIn("LIMIT 100", sql)
        self.assertEqual(params, (42, "AS_FOOD_GLOBAL", "ci-user"))
        self.assertNotIn("AS_FOOD_GLOBAL", sql)
        self.assertNotIn("ci-user", sql)

    def test_contact_query_joins_matching_customer_owner(self):
        cur = MagicMock()
        cur.fetchall.side_effect = [
            [("customers",), ("contacts",)],
            [(9, 3, "CI Person", "Contact", "", "ci@example.test", "")],
        ]
        cur.fetchone.return_value = (True,)
        with patch.object(crm, "authorize_company_on_cursor",
                          return_value=("ok", 6)):
            status, rows = crm.read_company_crm_on_cursor(
                cur, "ci-authorized", "AS_ILERI_GIDA", "İrtibat Kişileri"
            )
        self.assertEqual(status, "ok")
        self.assertEqual(rows[0]["name"], "CI Person")
        sql, args = cur.execute.call_args.args
        self.assertIn("p.id=b.customer_id", sql)
        self.assertIn("p.legal_entity_id=b.legal_entity_id", sql)
        self.assertEqual(args, (6, "AS_ILERI_GIDA", "ci-authorized"))

    def test_invalid_url_cannot_connect_and_no_sql_errors_returned(self):
        with patch("psycopg.connect") as connect:
            self.assertEqual(
                crm.read_company_crm(
                    "sqlite:///never", "ci-user", "AS_ILERI_GIDA", "Müşteriler"
                ), ("invalid_url", []),
            )
            connect.assert_not_called()

    def test_repository_function_never_modifies_business_data(self):
        from pathlib import Path
        code = (Path(__file__).resolve().parents[1] /
                "scripts/postgres_scoped_company_crm_read.py").read_text()
        for forbidden in (
            "INSERT INTO", "UPDATE \"ct_app\"", "ALTER TABLE",
            "CREATE TABLE", "DELETE FROM",
        ):
            self.assertNotIn(forbidden, code)
        self.assertIn("READ ONLY", code)


if __name__ == "__main__":
    unittest.main()
