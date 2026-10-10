"""Isolated SQLite integration checks using the real Control Tower business functions.

Never opens the application database or inserts demo records into production.
"""
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import control_tower as ct


class ControlTowerSqliteIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.db = Path(self.tmp.name) / "isolated_control_tower.db"
        db_patch = patch.object(ct, "DB_PATH", self.db)
        db_patch.start()
        self.addCleanup(db_patch.stop)
        ct.init_db()

    def sql(self, statement, params=()):
        with sqlite3.connect(self.db) as conn:
            conn.execute(statement, params)
            conn.commit()

    def count(self, table):
        with sqlite3.connect(self.db) as conn:
            return conn.execute("SELECT COUNT(*) FROM " + table).fetchone()[0]

    def prepare_order(self, quantity=1000, shipment=600):
        self.sql("INSERT INTO product_catalog (id,name,supplier) VALUES (1,'TEST PRODUCT','TEST SUPPLIER')")
        self.sql("INSERT INTO warehouses (id,name) VALUES (1,'TEST WAREHOUSE')")
        self.sql(
            "INSERT INTO purchase_orders "
            "(id,po_number,supplier,product_id,product_name,quantity_kg,unit_price,"
            "currency,destination_warehouse_id) VALUES "
            "(1,'TEST-PO','TEST SUPPLIER',1,'TEST PRODUCT',?,2.25,'EUR',1)",
            (quantity,),
        )
        self.sql(
            "INSERT INTO shipments "
            "(id,purchase_order_id,shipment_ref,quantity_kg,destination_warehouse_id)"
            " VALUES (1,1,'TEST-SHIPMENT',?,1)", (shipment,),
        )

    def test_new_database_contains_no_fictional_business_records(self):
        for table in ("customers", "product_catalog", "warehouses",
                      "purchase_orders", "shipments", "inventory_lots",
                      "quality_cases", "payables", "finance_transactions"):
            with self.subTest(table=table):
                self.assertEqual(self.count(table), 0)

    def test_receive_once_and_reconcile_stock_and_open_order(self):
        self.prepare_order()
        self.assertEqual(ct.receive_shipment_to_stock(1)[0], True)
        self.assertEqual(self.count("inventory_lots"), 1)
        self.assertEqual(ct.receive_shipment_to_stock(1)[0], False)
        self.assertEqual(self.count("inventory_lots"), 1)
        stock = ct.stock_snapshot()
        self.assertEqual(len(stock), 1)
        self.assertAlmostEqual(float(stock.iloc[0]["available_kg"]), 600)
        self.assertAlmostEqual(float(stock.iloc[0]["open_po_kg"]), 400)
        self.assertAlmostEqual(float(stock.iloc[0]["projected_stock_kg"]), 1000)
        with sqlite3.connect(self.db) as conn:
            status = conn.execute("SELECT status FROM purchase_orders WHERE id=1").fetchone()[0]
        self.assertEqual(status, "Kısmi Sevk")

    def test_quality_hold_reduces_sellable_stock_without_changing_physical_quantity(self):
        self.prepare_order()
        self.assertTrue(ct.receive_shipment_to_stock(1)[0])
        self.sql(
            "INSERT INTO quality_cases "
            "(id,case_no,opened_date,supplier,product_id,product_name,"
            "inventory_lot_id,purchase_order_id,shipment_id,affected_quantity_kg,description)"
            " VALUES (1,'TEST-QA','2026-10-10','TEST SUPPLIER',1,'TEST PRODUCT',"
            "1,1,1,100,'isolated quality hold test')"
        )
        self.sql(
            "UPDATE inventory_lots SET quality_status='HOLD',"
            "quality_case_id=1,quality_hold_kg=100 WHERE id=1"
        )
        stock = ct.stock_snapshot().iloc[0]
        self.assertEqual(float(stock["available_kg"]), 600)
        self.assertEqual(float(stock["quality_hold_kg"]), 100)
        self.assertEqual(float(stock["net_available_kg"]), 500)
        self.assertEqual(float(stock["projected_stock_kg"]), 900)
        self.assertEqual(len(ct.quality_case_summary()), 1)
        self.sql(
            "UPDATE inventory_lots SET quality_status='Released',"
            "quality_hold_kg=0 WHERE id=1"
        )
        released = ct.stock_snapshot().iloc[0]
        self.assertEqual(float(released["net_available_kg"]), 600)

    def test_payable_payment_updates_bank_and_ledger_once(self):
        self.prepare_order()
        self.assertTrue(ct.receive_shipment_to_stock(1)[0])
        self.sql("INSERT INTO cash_accounts (id,name,currency,balance) "
                 "VALUES (1,'TEST EUR BANK','EUR',10000)")
        self.sql("INSERT INTO payables "
                 "(id,supplier,purchase_order_id,due_date,amount,currency) "
                 "VALUES (1,'TEST SUPPLIER',1,'2026-12-01',2250,'EUR')")
        ok, _ = ct.record_payable_payment(
            1, 500, "2026-10-10", 1, "TEST-TRANSFER", "isolated test"
        )
        self.assertTrue(ok)
        self.assertFalse(ct.record_payable_payment(
            1, 100, "2026-10-10", 1, "TEST-TRANSFER", "duplicate replay"
        )[0])
        self.assertEqual(self.count("finance_transactions"), 1)
        self.assertEqual(self.count("finance_transactions"), 1)
        with sqlite3.connect(self.db) as conn:
            paid, status = conn.execute(
                "SELECT paid_amount,status FROM payables WHERE id=1"
            ).fetchone()
            balance = conn.execute(
                "SELECT balance FROM cash_accounts WHERE id=1"
            ).fetchone()[0]
        self.assertAlmostEqual(paid, 500)
        self.assertEqual(status, "Kısmi")
        self.assertAlmostEqual(balance, 9500)
        self.assertFalse(ct.record_payable_payment(
            1, 1800, "2026-10-10", 1, "OVERPAY", "test"
        )[0])
        self.assertEqual(self.count("finance_transactions"), 1)
        self.assertTrue(ct.record_payable_payment(
            1, 1750, "2026-10-10", 1, "FINAL", "test"
        )[0])
        self.assertFalse(ct.record_payable_payment(
            1, 1, "2026-10-10", 1, "REPLAY", "test"
        )[0])
        with sqlite3.connect(self.db) as conn:
            paid, status = conn.execute(
                "SELECT paid_amount,status FROM payables WHERE id=1"
            ).fetchone()
            balance = conn.execute(
                "SELECT balance FROM cash_accounts WHERE id=1"
            ).fetchone()[0]
        self.assertEqual((paid, status, balance), (2250, "Kapandı", 7750))
        self.assertEqual(self.count("finance_transactions"), 2)

    def test_receivable_reference_replay_is_blocked(self):
        self.sql("INSERT INTO customers (id,name) VALUES (1,'TEST CUSTOMER')")
        self.sql("INSERT INTO cash_accounts (id,name,currency,balance) "
                 "VALUES (1,'TEST EUR BANK','EUR',100)")
        self.sql("INSERT INTO receivables "
                 "(id,customer_id,due_date,amount,currency) "
                 "VALUES (1,1,'2026-12-01',1000,'EUR')")
        self.assertTrue(ct.record_receivable_payment(
            1, 200, "2026-10-10", 1, "BANK-RECEIPT-1", "first"
        )[0])
        self.assertFalse(ct.record_receivable_payment(
            1, 200, "2026-10-10", 1, "BANK-RECEIPT-1", "duplicate"
        )[0])
        with sqlite3.connect(self.db) as conn:
            paid = conn.execute(
                "SELECT paid_amount FROM receivables WHERE id=1"
            ).fetchone()[0]
            balance = conn.execute(
                "SELECT balance FROM cash_accounts WHERE id=1"
            ).fetchone()[0]
        self.assertEqual((paid, balance), (200, 300))
        self.assertEqual(self.count("finance_transactions"), 1)

    def test_currency_mismatch_cannot_debit_account(self):
        self.sql("INSERT INTO cash_accounts (id,name,currency,balance) "
                 "VALUES (1,'TEST USD BANK','USD',10000)")
        self.sql("INSERT INTO payables "
                 "(id,supplier,due_date,amount,currency) "
                 "VALUES (1,'TEST SUPPLIER','2026-12-01',100,'EUR')")
        self.assertFalse(ct.record_payable_payment(
            1, 50, "2026-10-10", 1, "MISMATCH", "test"
        )[0])
        self.assertEqual(self.count("finance_transactions"), 0)
        with sqlite3.connect(self.db) as conn:
            balance = conn.execute(
                "SELECT balance FROM cash_accounts WHERE id=1"
            ).fetchone()[0]
        self.assertEqual(balance, 10000)

    def test_over_receipt_rejected_without_inventory_mutation(self):
        self.prepare_order(quantity=500, shipment=600)
        self.assertEqual(ct.receive_shipment_to_stock(1)[0], False)
        self.assertEqual(self.count("inventory_lots"), 0)

    def test_cancelled_shipment_cannot_be_received(self):
        self.prepare_order()
        self.sql("UPDATE shipments SET status='İptal' WHERE id=1")
        self.assertEqual(ct.receive_shipment_to_stock(1)[0], False)
        self.assertEqual(self.count("inventory_lots"), 0)


if __name__ == "__main__":
    unittest.main()
