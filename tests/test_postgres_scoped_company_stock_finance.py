"""Offline tests for new company-scoped stock, QA and settlement routines."""
import unittest
from decimal import Decimal
from unittest.mock import MagicMock

from scripts import postgres_scoped_company_write_rehearsal as w


class CompanyStockFinanceSafetyTests(unittest.TestCase):
    def test_five_operations_registered_for_exact_roles_and_audit(self):
        expected = {
            "receive_shipment": ("PURCHASING", "inventory_lots"),
            "hold_inventory_lot": ("QUALITY", "quality_cases"),
            "release_inventory_lot": ("QUALITY", "quality_cases"),
            "pay_supplier": ("FINANCE", "finance_transactions"),
            "collect_customer_payment": ("FINANCE", "finance_transactions"),
        }
        for operation, (role, table) in expected.items():
            with self.subTest(operation=operation):
                self.assertIn(role, w._ALLOWED[operation])
                self.assertNotIn("VIEWER", w._ALLOWED[operation])
                self.assertEqual(w._ACTION_TABLE[operation], table)

    def test_wrong_company_shipment_never_moves_stock(self):
        cur = MagicMock()
        cur.fetchone.return_value = None
        with self.assertRaises(w.ScopedWriteDenied) as ctx:
            w.receive_shipment_on_cursor(cur, 22, shipment_id=9)
        self.assertEqual(ctx.exception.code, "wrong_company_shipment")
        self.assertEqual(cur.execute.call_count, 1)
        self.assertIn("legal_entity_id=%s", cur.execute.call_args.args[0])
        self.assertEqual(cur.execute.call_args.args[1], (9, 22))

    def test_wrong_company_lot_never_opens_quality_case(self):
        cur = MagicMock()
        cur.fetchone.return_value = None
        with self.assertRaises(w.ScopedWriteDenied) as ctx:
            w.hold_inventory_lot_on_cursor(
                cur, 22, lot_id=99, case_no="CI-01", hold_kg=1,
                reason="CI synthetic"
            )
        self.assertEqual(ctx.exception.code, "wrong_company_lot")
        self.assertEqual(cur.execute.call_count, 1)
        self.assertIn("legal_entity_id=%s", cur.execute.call_args.args[0])

    def test_wrong_company_release_does_not_change_other_lot(self):
        cur = MagicMock()
        cur.fetchone.return_value = None
        with self.assertRaises(w.ScopedWriteDenied) as ctx:
            w.release_inventory_lot_on_cursor(
                cur, 22, lot_id=55, resolution="CI synthetic"
            )
        self.assertEqual(ctx.exception.code, "wrong_company_lot")
        self.assertEqual(cur.execute.call_count, 1)
        self.assertIn("legal_entity_id=%s", cur.execute.call_args.args[0])

    def test_payable_from_other_company_does_not_touch_bank(self):
        cur = MagicMock()
        cur.fetchone.return_value = None
        with self.assertRaises(w.ScopedWriteDenied) as ctx:
            w.pay_supplier_on_cursor(
                cur, 22, payable_id=51, account_id=7, amount=10,
                reference="CI-REMIT", payment_date="2026-10-11"
            )
        self.assertEqual(ctx.exception.code, "wrong_company_payable")
        self.assertEqual(cur.execute.call_count, 1)
        self.assertIn("legal_entity_id=%s", cur.execute.call_args.args[0])

    def test_quality_hold_blocks_payment_before_cash_lookup(self):
        cur = MagicMock()
        cur.fetchone.side_effect = [
            (42, Decimal("20"), Decimal("0"), "EUR", "Açık"),
            (True,),
        ]
        with self.assertRaises(w.ScopedWriteDenied) as ctx:
            w.pay_supplier_on_cursor(
                cur, 22, payable_id=51, account_id=7, amount=10,
                reference="CI-REMIT", payment_date="2026-10-11"
            )
        self.assertEqual(ctx.exception.code, "quality_hold_blocks_payment")
        self.assertEqual(cur.execute.call_count, 2)
        for call in cur.execute.call_args_list:
            self.assertIn("legal_entity_id=%s", call.args[0])

    def test_cross_company_receivable_rejected_before_bank_read(self):
        cur = MagicMock()
        cur.fetchone.return_value = None
        with self.assertRaises(w.ScopedWriteDenied) as ctx:
            w.collect_customer_payment_on_cursor(
                cur, 22, receivable_id=14, account_id=1, amount=1,
                reference="CI-AR-REF", payment_date="2026-10-11"
            )
        self.assertEqual(ctx.exception.code, "wrong_company_receivable")
        self.assertEqual(cur.execute.call_count, 1)
        self.assertIn("legal_entity_id=%s", cur.execute.call_args.args[0])

    def test_bank_owner_is_required_even_when_caller_has_company_grant(self):
        cur = MagicMock()
        cur.fetchone.return_value = None
        with self.assertRaises(w.ScopedWriteDenied) as ctx:
            w._company_bank_for_update(cur, 22, 77)
        self.assertEqual(ctx.exception.code, "wrong_company_account")
        self.assertEqual(cur.execute.call_args.args[1], (77, 22))

    def test_invalid_input_does_not_create_transactions(self):
        cur=MagicMock()
        with self.assertRaises(w.ScopedWriteDenied):
            w.receive_shipment_on_cursor(cur,22,shipment_id=True)
        with self.assertRaises(w.ScopedWriteDenied):
            w.collect_customer_payment_on_cursor(
                cur,22,receivable_id=1,account_id=2,amount=-1,
                reference="R",payment_date="2026-10-11"
            )
        cur.execute.assert_not_called()


if __name__ == "__main__":
    unittest.main()
