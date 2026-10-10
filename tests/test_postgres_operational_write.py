"""Isolated offline tests for the real ct_app transactional write engine.

All psycopg connections are mocks: no Supabase URI or company data is used.
"""
import os
import unittest
from decimal import Decimal
from unittest.mock import MagicMock, patch

from scripts import postgres_operational_write as op

URL = "postgresql://user:private-secret@localhost/db"


class OperationalWriteTests(unittest.TestCase):
    def setUp(self):
        self.env = patch.dict(os.environ, {"AS_CONTROL_TOWER_PG_WRITES_ENABLED": "1"})
        self.env.start()
        self.addCleanup(self.env.stop)
        self.schema = patch.object(
            op, "validate_staging_structure", return_value=("ok", [])
        )
        self.schema_mock = self.schema.start()
        self.addCleanup(self.schema.stop)
        self.connect_patch = patch("psycopg.connect")
        self.connect = self.connect_patch.start()
        self.addCleanup(self.connect_patch.stop)
        self.conn = self.connect.return_value.__enter__.return_value
        self.cur = self.conn.cursor.return_value.__enter__.return_value

    def rows(self, *rows):
        self.cur.fetchone.side_effect = rows

    def statements(self):
        return [c.args[0] for c in self.cur.execute.call_args_list]

    def test_forbidden_role_does_not_open_connection_or_check_schema(self):
        self.assertEqual(
            op.create_customer(URL, "VIEWER", "SECRET COMPANY"),
            ("forbidden", None),
        )
        self.assertEqual(
            op.pay_supplier(URL, "PURCHASING", 1, 2, 100, "REF", "2026-10-10"),
            ("forbidden", None),
        )
        self.schema_mock.assert_not_called()
        self.connect.assert_not_called()

    def test_all_write_endpoints_are_disabled_by_default(self):
        with patch.dict(os.environ, {"AS_CONTROL_TOWER_PG_WRITES_ENABLED": "0"}):
            self.assertEqual(
                op.create_customer(URL, "ADMIN", "SAFE"), ("disabled", None)
            )
            self.assertEqual(
                op.pay_supplier(URL, "FINANCE", 1, 1, 100, "X", "2026-10-10"),
                ("disabled", None),
            )
        self.connect.assert_not_called()
        self.schema_mock.assert_not_called()

    def test_invalid_url_fails_before_schema_or_connection(self):
        self.assertEqual(
            op.create_product("sqlite:///db", "ADMIN", "X", "Supplier"),
            ("invalid_url", None),
        )
        self.connect.assert_not_called()
        self.schema_mock.assert_not_called()

    def test_schema_mismatch_blocks_writes(self):
        self.schema_mock.return_value = ("mismatch", [])
        self.assertEqual(
            op.create_customer(URL, "ADMIN", "X"),
            ("schema_mismatch", None),
        )
        self.connect.assert_not_called()

    def test_new_customer_serializes_duplicate_name_check(self):
        self.rows(None, (41,))
        status, ident = op.create_customer(URL, "SALES", "Example Customer")
        self.assertEqual((status, ident), ("ok", 41))
        statements = self.statements()
        self.assertIn("pg_advisory_xact_lock", statements[3])
        self.assertIn('"ct_app"."customers"', statements[5])
        self.assertIn("RETURNING id", statements[5])
        self.conn.transaction.assert_called_once()

    def test_duplicate_customer_rejected_without_insert(self):
        self.rows((8,))
        self.assertEqual(
            op.create_customer(URL, "ADMIN", "Existing"), ("duplicate_customer", None)
        )
        self.assertFalse(any(s.startswith("INSERT ") for s in self.statements()))
        # The transaction context handles rollback on OperationRejected.
        self.assertTrue(self.conn.transaction.return_value.__exit__.called)

    def test_product_name_uniqueness_checked(self):
        self.rows(None, (13,))
        self.assertEqual(
            op.create_product(URL, "PURCHASING", "Product", "Supplier"),
            ("ok", 13),
        )
        self.assertTrue(any(
            'INSERT INTO "ct_app"."product_catalog"' in s for s in self.statements()
        ))

    def test_create_warehouse_writes_atomic_audit_with_actor(self):
        self.rows(None, (52,))
        status, ident = op.create_warehouse(
            URL, "PURCHASING", "CI FAKE WAREHOUSE",
            city="London", warehouse_type="Normal Depo",
            actor="ci-purchaser",
        )
        self.assertEqual((status, ident), ("ok", 52))
        calls = self.cur.execute.call_args_list
        self.assertTrue(any(
            'INSERT INTO "ct_app"."warehouses"' in call.args[0]
            for call in calls
        ))
        audit = [call for call in calls if
                 'INSERT INTO "ct_app"."audit_log"' in call.args[0]]
        self.assertEqual(len(audit), 1)
        self.assertEqual(
            audit[0].args[1],
            ("ci-purchaser", "PURCHASING", "create_warehouse", "warehouses"),
        )

    def test_duplicate_warehouse_has_no_mutation_or_audit(self):
        self.rows((55,))
        self.assertEqual(
            op.create_warehouse(
                URL, "ADMIN", "CI EXISTING WAREHOUSE", actor="ci-admin"
            ),
            ("duplicate_warehouse", None),
        )
        self.assertFalse(any(
            stmt.startswith("INSERT ") for stmt in self.statements()
        ))

    def test_audit_failure_rejects_operation_and_keeps_atomic_scope(self):
        self.rows(None, (9,))
        def maybe_fail(sql, *args):
            if 'INSERT INTO "ct_app"."audit_log"' in sql:
                raise RuntimeError("sensitive database exception")
        self.cur.execute.side_effect = maybe_fail
        result = op.create_customer(
            URL, "ADMIN", "CI ROLLBACK CUSTOMER", actor="ci-admin"
        )
        self.assertEqual(result, ("failed", None))
        self.assertTrue(self.conn.transaction.called)
        self.assertNotIn("sensitive", str(result))

    def test_new_purchase_order_checks_active_product_and_warehouse(self):
        self.rows(("Sugar",), (9,), None, (66,))
        self.assertEqual(
            op.create_purchase_order(
                URL, "PURCHASING", "PO-1", "Supplier", 2, 9,
                Decimal("1000.0"), "2.5", "EUR"
            ),
            ("ok", 66),
        )
        self.assertTrue(any(
            'INSERT INTO "ct_app"."purchase_orders"' in s
            for s in self.statements()
        ))

    def test_invalid_purchase_amount_fails_without_insert(self):
        self.assertEqual(
            op.create_purchase_order(
                URL, "ADMIN", "PO-1", "Supplier", 1, 1, "NaN", 1, "USD",
            ),
            ("invalid_amount", None),
        )
        self.assertFalse(any(s.startswith("INSERT ") for s in self.statements()))

    def test_shipment_cannot_exceed_order_and_does_not_insert(self):
        self.rows((1000, "Sipariş Verildi", 1), (950,))
        self.assertEqual(
            op.create_shipment(URL, "PURCHASING", 10, "SHIP-01", 100),
            ("over_shipment", None),
        )
        self.assertFalse(any(s.startswith("INSERT ") for s in self.statements()))

    def test_shipment_creation_locks_purchase_order(self):
        self.rows((1000, "Sipariş Verildi", 1), (0,), None, (37,))
        self.assertEqual(
            op.create_shipment(URL, "ADMIN", 10, "SHIP-01", 600), ("ok", 37)
        )
        self.assertTrue(any(
            'purchase_orders" WHERE id=%s FOR UPDATE' in s
            for s in self.statements()
        ))

    def test_receipt_posts_lot_and_marks_shipment_in_one_transaction(self):
        self.rows(
            (10,),  # shipment -> po
            (1, "Sugar", 1000, 2.25, "EUR", 5, "Sipariş Verildi"),
            (10, 600, 0, "Planlandı", 5, "LOT-1", "2027-12-30"),
            (0,),  # already received qty
            (77,),  # new inventory id
        )
        self.assertEqual(op.receive_shipment(URL, "PURCHASING", 23), ("ok", 77))
        statements = self.statements()
        self.assertTrue(any("inventory_lots" in s and "INSERT" in s for s in statements))
        self.assertTrue(any('UPDATE "ct_app"."shipments"' in s for s in statements))
        self.assertTrue(any('UPDATE "ct_app"."purchase_orders"' in s for s in statements))
        self.conn.transaction.assert_called_once()

    def test_receipt_replay_refused_without_writes(self):
        self.rows(
            (10,),
            (1, "Sugar", 1000, 2.25, "EUR", 5, "Sipariş Verildi"),
            (10, 600, 1, "Teslim Edildi", 5, "", ""),
        )
        self.assertEqual(
            op.receive_shipment(URL, "PURCHASING", 23),
            ("already_received_or_cancelled", None),
        )
        self.assertFalse(any(s.startswith("INSERT ") for s in self.statements()))

    def test_quality_hold_updates_lot_and_case_atomically(self):
        self.rows(
            (1, "Sugar", 600, 0, "Released", 0, 10, 23),
            (44,),
        )
        self.assertEqual(
            op.hold_inventory_lot(URL, "QUALITY", 77, "QA-1", 100, "Issue"),
            ("ok", 44),
        )
        self.assertTrue(any('INSERT INTO "ct_app"."quality_cases"' in s
                            for s in self.statements()))
        self.assertTrue(any('UPDATE "ct_app"."inventory_lots"' in s
                            for s in self.statements()))

    def test_quality_hold_larger_than_available_rejected(self):
        self.rows((1, "Sugar", 600, 200, "Released", 0, 10, 23))
        self.assertEqual(
            op.hold_inventory_lot(URL, "ADMIN", 77, "QA-1", 500, "Issue"),
            ("hold_exceeds_available", None),
        )
        self.assertFalse(any(s.startswith("INSERT ") for s in self.statements()))

    def test_quality_release_closes_correct_case_and_unblocks_stock(self):
        self.rows(("HOLD", 44), (77, "Açık"))
        self.assertEqual(
            op.release_inventory_lot(URL, "QUALITY", 77, "Supplier replacement approved"),
            ("ok", 44),
        )
        self.assertTrue(any(
            'UPDATE "ct_app"."quality_cases"' in stmt
            for stmt in self.statements()
        ))
        self.assertTrue(any(
            'UPDATE "ct_app"."inventory_lots"' in stmt
            for stmt in self.statements()
        ))

    def test_quality_release_replay_or_unrelated_case_is_rejected(self):
        self.rows(("Released", 44))
        self.assertEqual(
            op.release_inventory_lot(URL, "ADMIN", 77, "Repeat"),
            ("lot_not_on_hold", None),
        )
        self.assertFalse(any(stmt.startswith("UPDATE ") for stmt in self.statements()))

        self.cur.reset_mock()
        self.rows(("HOLD", 44), (88, "Açık"))
        self.assertEqual(
            op.release_inventory_lot(URL, "QUALITY", 77, "Wrong case"),
            ("case_mismatch", None),
        )
        self.assertFalse(any(stmt.startswith("UPDATE ") for stmt in self.statements()))

    def test_viewer_cannot_release_quality_hold(self):
        self.assertEqual(
            op.release_inventory_lot(URL, "VIEWER", 77, "Not authorized"),
            ("forbidden", None),
        )
        self.connect.assert_not_called()

    def test_invoice_duplicate_protection(self):
        self.rows(("Supplier",), None, (91,))
        self.assertEqual(
            op.create_payable(
                URL, "FINANCE", "Supplier", 10, "INV-1", "2026-12-01",
                1500, "EUR"
            ), ("ok", 91),
        )
        self.assertTrue(any("pg_advisory_xact_lock" in s
                            for s in self.statements()))

    def test_payment_blocks_held_quality_lot(self):
        self.rows(
            (10, 1500, 0, "EUR", "Açık"),
            (True,),
        )
        self.assertEqual(
            op.pay_supplier(
                URL, "FINANCE", 91, 3, 500, "TRX-1", "2026-10-10"
            ), ("quality_hold_blocks_payment", None),
        )
        self.assertFalse(any(s.startswith("UPDATE ") for s in self.statements()))

    def test_payment_amount_and_reference_settlement(self):
        self.rows(
            (10, 1500, 0, "EUR", "Açık"),
            (False,),  # quality hold?
            ("EUR", 600, 1),  # account
            None,  # duplicate reference?
            (88,),  # transaction ID
        )
        self.assertEqual(
            op.pay_supplier(
                URL, "FINANCE", 91, 3, 500, "TRX-1", "2026-10-10"
            ), ("ok", 88),
        )
        stmts = self.statements()
        self.assertTrue(any('UPDATE "ct_app"."payables"' in s for s in stmts))
        self.assertTrue(any('INSERT INTO "ct_app"."finance_transactions"' in s
                            for s in stmts))
        self.assertTrue(any('UPDATE "ct_app"."cash_accounts"' in s for s in stmts))
        self.assertTrue(any('FOR UPDATE' in s for s in stmts))

    def test_duplicate_payment_ref_does_not_debit_twice(self):
        self.rows(
            (10, 1500, 100, "EUR", "Kısmi"),
            (False,),
            ("EUR", 1000, 1),
            (1,),  # previous payment reference
        )
        self.assertEqual(
            op.pay_supplier(
                URL, "FINANCE", 91, 3, 500, "TRX-1", "2026-10-10"
            ), ("duplicate_payment", None),
        )
        self.assertFalse(any(s.startswith("UPDATE ") for s in self.statements()))

    def test_failed_connection_does_not_leak_credentials(self):
        self.connect.side_effect = RuntimeError("password private-secret")
        answer = op.create_customer(URL, "ADMIN", "PRIVATE CUSTOMER")
        self.assertEqual(answer, ("failed", None))
        self.assertNotIn("private-secret", str(answer))

    def test_validation_limits_nan_and_invalid_ids(self):
        with self.assertRaises(op.OperationRejected):
            op._positive("-1")
        with self.assertRaises(op.OperationRejected):
            op._positive("nan")
        with self.assertRaises(op.OperationRejected):
            op._id(True)
        with self.assertRaises(op.OperationRejected):
            op._date("2026-99-99")


if __name__ == "__main__":
    unittest.main()
