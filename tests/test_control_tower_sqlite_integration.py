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
