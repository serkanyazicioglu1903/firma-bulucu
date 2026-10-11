"""Offline tests for CI-only, audited four-company CRM creation."""
import os
from pathlib import Path
import unittest
from unittest.mock import MagicMock, patch

from scripts import postgres_scoped_company_crm_write_rehearsal as crm

CI_URL = "postgresql://ct_ci:ci-dummy-only@127.0.0.1:5432/ct_ci_control_tower"
PROD_URL = "postgresql://postgres:password@db.supabase.co:5432/postgres"


class CompanyCrmWriteSafetyTests(unittest.TestCase):
    @patch("psycopg.connect")
    def test_production_url_is_never_connected_even_with_ci_flags(self, connect):
        with patch.dict(os.environ, {
            "CT_LOCAL_POSTGRES_TEST": "1",
            "AS_CONTROL_TOWER_PG_WRITES_ENABLED": "1",
            "CT_TEST_DATABASE_URL": PROD_URL,
        }):
            self.assertEqual(
                crm.run_company_crm_write_rehearsal(
                    PROD_URL, "ci-admin", "AS_ILERI_GIDA", "ADMIN",
                    "create_customer", name="CI Test Company"
                ),
                ("disabled", None),
            )
        connect.assert_not_called()

    @patch("psycopg.connect")
    def test_disabled_ci_or_wrong_role_never_connects(self, connect):
        with patch.dict(os.environ, {
            "CT_LOCAL_POSTGRES_TEST": "0",
            "AS_CONTROL_TOWER_PG_WRITES_ENABLED": "1",
            "CT_TEST_DATABASE_URL": CI_URL,
        }):
            self.assertEqual(
                crm.run_company_crm_write_rehearsal(
                    CI_URL, "ci-admin", "AS_ILERI_GIDA", "ADMIN",
                    "create_customer", name="CI Test Company"
                ), ("disabled", None),
            )
        invalid = (
            ("ci-admin", "AS_ILERI_GIDA", "SALES", "create_customer"),
            ("ci-admin", "AS_ILERI_GIDA", "PURCHASING", "create_contact"),
            ("bad user with spaces", "AS_ILERI_GIDA", "ADMIN", "create_contact"),
            ("ci-admin", "UNKNOWN", "ADMIN", "create_customer"),
            ("ci-admin", "AS_ILERI_GIDA", "ADMIN", "other_operation"),
        )
        for principal, company, role, action in invalid:
            with self.subTest(role=role, action=action):
                self.assertEqual(
                    crm.run_company_crm_write_rehearsal(
                        CI_URL, principal, company, role, action
                    ), ("forbidden", None),
                )
        connect.assert_not_called()

    @patch.object(crm, "company_crm_structure_ready_on_cursor",
                  return_value=True)
    @patch.object(crm, "_owner_and_writer", return_value=42)
    def test_create_customer_is_owned_and_audited(self, owner, ready):
        cur = MagicMock()
        cur.fetchone.return_value = (17,)
        identifier = crm.run_company_crm_write_on_cursor(
            cur, "ci-admin", "AS_FOOD_GLOBAL", "ADMIN",
            "create_customer", name=" CI Fictional Distributor ",
            country="GB", sector="Biscuit", currency="GBP",
        )
        self.assertEqual(identifier, 17)
        self.assertEqual(cur.execute.call_count, 2)
        stmt, params = cur.execute.call_args_list[0].args
        self.assertIn('"ct_app"."customers"', stmt)
        self.assertIn("legal_entity_id", stmt)
        self.assertEqual(params[-1], 42)
        self.assertEqual(params[0], "CI Fictional Distributor")
        audit_sql, audit = cur.execute.call_args_list[1].args
        self.assertIn('"ct_app"."company_operation_audit"', audit_sql)
        self.assertEqual(
            audit, ("ci-admin", 42, "create_customer", "customers", 17)
        )
        owner.assert_called_once_with(cur, "ci-admin", "AS_FOOD_GLOBAL")
        ready.assert_called_once_with(cur)

    @patch.object(crm, "company_crm_structure_ready_on_cursor",
                  return_value=False)
    @patch.object(crm, "_owner_and_writer", return_value=42)
    def test_missing_crm_ownership_stops_insert_and_audit(self, owner, ready):
        cur = MagicMock()
        with self.assertRaises(crm.ScopedWriteDenied) as error:
            crm.run_company_crm_write_on_cursor(
                cur, "ci-admin", "AS_ILERI_GIDA", "ADMIN",
                "create_customer", name="Fictional Only",
            )
        self.assertEqual(error.exception.code, "not_ready")
        cur.execute.assert_not_called()
        cur.fetchone.assert_not_called()

    @patch.object(crm, "company_crm_structure_ready_on_cursor",
                  return_value=True)
    @patch.object(crm, "_owner_and_writer", return_value=42)
    def test_wrong_company_customer_denied_before_contact_insert(
        self, owner, ready,
    ):
        cur = MagicMock()
        cur.fetchone.return_value = None
        with self.assertRaises(crm.ScopedWriteDenied) as error:
            crm.run_company_crm_write_on_cursor(
                cur, "ci-admin", "AS_ILERI_GIDA", "ADMIN",
                "create_contact", customer_id=999, name="Other Company Person",
            )
        self.assertEqual(error.exception.code, "wrong_company_customer")
        self.assertEqual(cur.execute.call_count, 1)
        query, params = cur.execute.call_args.args
        self.assertIn("legal_entity_id=%s", query)
        self.assertEqual(params, (999, 42))
        self.assertNotIn("INSERT INTO", query)

    @patch.object(crm, "company_crm_structure_ready_on_cursor",
                  return_value=True)
    @patch.object(crm, "_owner_and_writer", return_value=42)
    def test_created_contact_audited_after_parent_company_check(
        self, owner, ready,
    ):
        cur = MagicMock()
        cur.fetchone.side_effect = [(101,), (505,)]
        ident = crm.run_company_crm_write_on_cursor(
            cur, "ci-admin", "AS_ILERI_GIDA", "ADMIN",
            "create_contact", customer_id=101, name="CI Example Person",
            email="example@ci.invalid",
        )
        self.assertEqual(ident, 505)
        self.assertEqual(cur.execute.call_count, 3)
        stmt, params = cur.execute.call_args_list[1].args
        self.assertIn('"ct_app"."contacts"', stmt)
        self.assertEqual(params[-1], 42)
        self.assertEqual(params[0], 101)
        self.assertEqual(
            cur.execute.call_args_list[-1].args[1],
            ("ci-admin", 42, "create_contact", "contacts", 505),
        )

    def test_invalid_text_and_keys_denied_with_no_statements(self):
        for value in ("", " ", "Invalid\nHeader", "x" * 251):
            with self.subTest(value=value[:20]):
                cur = MagicMock()
                with self.assertRaises(crm.ScopedWriteDenied):
                    crm.create_customer_on_cursor(cur, 1, name=value)
                cur.execute.assert_not_called()
        for fake in (None, True, 0, -1, "1"):
            with self.subTest(customer_id=fake):
                cur = MagicMock()
                with self.assertRaises(crm.ScopedWriteDenied):
                    crm.create_contact_on_cursor(
                        cur, 1, customer_id=fake, name="Fictional Contact"
                    )
                cur.execute.assert_not_called()

    def test_no_streamlit_and_no_unbounded_database_entrypoint(self):
        src = (Path(__file__).resolve().parents[1] / "scripts"
               / "postgres_scoped_company_crm_write_rehearsal.py").read_text()
        self.assertNotIn("import streamlit", src)
        self.assertNotIn("DATABASE_URL", src)
        self.assertIn("_valid_disposable_test_target(url)", src)


if __name__ == "__main__":
    unittest.main()
