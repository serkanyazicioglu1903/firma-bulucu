"""CI-only write adapter: no real Supabase connection and no invented grants."""
import os
import unittest
from unittest.mock import MagicMock, patch

from scripts import postgres_scoped_company_write_rehearsal as wr

CI_URL = "postgresql://ct_ci:ci-dummy-only@127.0.0.1:5432/ct_ci_control_tower"
PROD_URL = "postgresql://postgres:private-password@db.supabase.co:5432/postgres"


class FourCompanyAtomicWriteOfflineTests(unittest.TestCase):
    def test_ddl_does_not_insert_users_or_enable_writes(self):
        statements = wr.rehearsal_extra_ddl()
        self.assertEqual(len(statements), 3)
        self.assertIn("can_write BOOLEAN NOT NULL DEFAULT FALSE", statements[0])
        self.assertIn("PRIMARY KEY (warehouse_id,legal_entity_id)", statements[1])
        self.assertIn("company_operation_audit", statements[2])
        self.assertFalse(any(
            keyword in stmt for stmt in statements
            for keyword in ("INSERT INTO", "GRANT ALL", "CREATE USER")
        ))

    def test_disposable_url_gate_rejects_even_spoofed_production(self):
        with patch.dict(os.environ, {
            "CT_LOCAL_POSTGRES_TEST": "1",
            "AS_CONTROL_TOWER_PG_WRITES_ENABLED": "1",
            "CT_TEST_DATABASE_URL": PROD_URL,
        }):
            self.assertFalse(wr._valid_disposable_test_target(PROD_URL))
        with patch.dict(os.environ, {
            "CT_LOCAL_POSTGRES_TEST": "1",
            "AS_CONTROL_TOWER_PG_WRITES_ENABLED": "1",
            "CT_TEST_DATABASE_URL": CI_URL,
        }):
            self.assertTrue(wr._valid_disposable_test_target(CI_URL))
            self.assertFalse(wr._valid_disposable_test_target(PROD_URL))
        with patch.dict(os.environ, {
            "CT_LOCAL_POSTGRES_TEST": "0",
            "CT_TEST_DATABASE_URL": CI_URL,
        }):
            self.assertFalse(wr._valid_disposable_test_target(CI_URL))

    def test_live_or_disabled_urls_never_open_database(self):
        with patch("psycopg.connect") as connect:
            with patch.dict(os.environ, {"CT_LOCAL_POSTGRES_TEST":"0"}):
                self.assertEqual(
                    wr.run_scoped_write_rehearsal(
                        PROD_URL, "ci-admin", "AS_FOOD_GLOBAL", "ADMIN",
                        "create_purchase_order",
                    ), ("disabled", None)
                )
            connect.assert_not_called()

    def test_bad_role_principal_company_operation_never_connect(self):
        bad = (
            ("ci-user", "AS_ILERI_GIDA", "VIEWER", "create_purchase_order"),
            ("ci-user", "AS_ILERI_GIDA", "PURCHASING", "pay_supplier"),
            ("ci-user", "UNKNOWN", "ADMIN", "create_purchase_order"),
            ("' OR TRUE --", "AS_ILERI_GIDA", "ADMIN", "create_purchase_order"),
            ("ci-user", ["AS_ILERI_GIDA"], "ADMIN", "create_purchase_order"),
            ("ci-user", "AS_ILERI_GIDA", ["ADMIN"], "create_purchase_order"),
            ("ci-user", "AS_ILERI_GIDA", "ADMIN", []),
        )
        with patch("psycopg.connect") as connect:
            for principal, company, role, operation in bad:
                with self.subTest(role=role,operation=operation):
                    self.assertEqual(
                        wr.run_scoped_write_rehearsal(
                            PROD_URL, principal, company, role, operation
                        ), ("forbidden", None)
                    )
            connect.assert_not_called()

    @patch.object(wr, "_owner_and_writer", return_value=42)
    def test_atomic_writer_calls_audit_only_after_permitted_operation(self, check):
        cur = MagicMock()
        with patch.dict(wr._ACTIONS, {"create_shipment":lambda c, company, **kw: 99}):
            ident = wr.run_scoped_write_on_cursor(
                cur, "ci-user", "AS_FOOD_GLOBAL", "PURCHASING",
                "create_shipment", purchase_order_id=5,
            )
        self.assertEqual(ident, 99)
        check.assert_called_once_with(cur, "ci-user", "AS_FOOD_GLOBAL")
        sql, params = cur.execute.call_args.args
        self.assertIn('"ct_app"."company_operation_audit"', sql)
        self.assertEqual(
            params,
            ("ci-user",42,"create_shipment","shipments",99),
        )

    @patch.object(wr, "_owner_and_writer", return_value=42)
    def test_failed_insert_must_not_audit(self, check):
        cur = MagicMock()
        def fail(_c, _company, **_kwargs):
            raise wr.ScopedWriteDenied("wrong_company_po")
        with patch.dict(wr._ACTIONS, {"create_shipment":fail}):
            with self.assertRaises(wr.ScopedWriteDenied) as ctx:
                wr.run_scoped_write_on_cursor(
                    cur, "ci-user", "AS_FOOD_GLOBAL", "PURCHASING",
                    "create_shipment", purchase_order_id=5,
                )
        self.assertEqual(ctx.exception.code, "wrong_company_po")
        cur.execute.assert_not_called()

    @patch.object(wr, "authorize_company_on_cursor", return_value=("ok", 42))
    def test_read_grant_without_write_grant_is_not_enough(self, _auth):
        cur = MagicMock()
        cur.fetchone.side_effect = [(True,True,True), None]
        with self.assertRaises(wr.ScopedWriteDenied) as ctx:
            wr._owner_and_writer(cur, "ci-user", "AS_ILERI_HOLDING")
        self.assertEqual(ctx.exception.code, "forbidden")
        sql, params = cur.execute.call_args.args
        self.assertIn("FOR SHARE OF e,r,w", sql)
        self.assertIn("w.can_write=TRUE", sql)
        self.assertIn("r.can_read=TRUE", sql)
        self.assertEqual(params,(42,"AS_ILERI_HOLDING","ci-user","ci-user"))


if __name__ == "__main__":
    unittest.main()
