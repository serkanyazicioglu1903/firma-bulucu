"""Real PostgreSQL transaction test using a disposable GitHub Actions service.

NEVER connects to Supabase: strict loopback, database-name, username and
explicit CI toggle are checked before creating ANY schema or data. The service
database is destroyed by GitHub Actions after the job. Production SSL is still
required everywhere except this deliberately restricted local Docker test.
"""
import os
from decimal import Decimal
from urllib.parse import urlsplit
import unittest

from scripts.build_pg_schema import quote
from scripts.postgres_connection import sslmode_for, CI_DATABASE, CI_USER
from scripts.postgres_live_schema import schema_ddl_steps
from scripts.staging_validate import validate_staging_structure
from scripts.postgres_operational_write import (
    create_customer, create_product, create_purchase_order, create_shipment,
    receive_shipment, hold_inventory_lot, release_inventory_lot,
    create_payable, pay_supplier,
)
from scripts.postgres_operational_read import read_operational_counts


def validated_ci_url():
    url = os.environ.get("CT_TEST_DATABASE_URL", "")
    try:
        parsed = urlsplit(url)
        allowed = (
            os.environ.get("CT_LOCAL_POSTGRES_TEST") == "1"
            and os.environ.get("AS_CONTROL_TOWER_PG_WRITES_ENABLED") == "1"
            and parsed.scheme in ("postgres", "postgresql")
            and parsed.hostname in ("127.0.0.1", "localhost")
            and parsed.port == 5432
            and parsed.username == CI_USER
            and parsed.path == "/" + CI_DATABASE
            and sslmode_for(url) == "disable"
        )
    except ValueError:
        allowed = False
    if not allowed:
        raise unittest.SkipTest("Only the local, disposable CI PostgreSQL database is permitted.")
    return url


class RealPostgresOperationalIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.url = validated_ci_url()
        import psycopg
        cls.conn = psycopg.connect(
            cls.url, sslmode=sslmode_for(cls.url), connect_timeout=8,
            autocommit=True,
        )
        tables, ddl, foreign_keys = schema_ddl_steps()
        if len(tables) != 26:
            raise AssertionError("Expected 26 tables")
        with cls.conn.transaction():
            with cls.conn.cursor() as cur:
                # Never DROP/modify an existing schema, even in CI.
                cur.execute(
                    "SELECT EXISTS (SELECT 1 FROM pg_namespace WHERE nspname=%s)",
                    ("ct_app",),
                )
                if cur.fetchone()[0]:
                    raise AssertionError("ct_app already exists; refusing to touch data.")
                cur.execute('CREATE SCHEMA "ct_app"')
                cur.execute('SET LOCAL search_path TO "ct_app", pg_catalog')
                for statement in ddl + foreign_keys:
                    cur.execute(statement)
        status, issues = validate_staging_structure(cls.url, schema="ct_app")
        if status != "ok":
            raise AssertionError("Live ct_app schema failed its structural check.")
 
    @classmethod
    def tearDownClass(cls):
        if hasattr(cls, "conn"):
            cls.conn.close()

    def execute(self, sql, parameters=()):
        with self.conn.cursor() as cur:
            cur.execute(sql, parameters)
            if sql.lstrip().upper().startswith("SELECT"):
                return cur.fetchone()
            return None

    def test_actual_crm_purchase_stock_quality_and_finance(self):
        customer = create_customer(self.url, "SALES", "CI FICTIONAL CUSTOMER")
        self.assertEqual(customer[0], "ok", customer[0])
        self.assertEqual(
            create_customer(self.url, "ADMIN", "ci fictional customer")[0],
            "duplicate_customer",
        )
        product = create_product(
            self.url, "PURCHASING", "CI FAKE INGREDIENT", "CI FAKE SUPPLIER"
        )
        self.assertEqual(product[0], "ok", product[0])
        self.execute(
            'INSERT INTO "ct_app"."warehouses" (name) VALUES (%s)',
            ("CI FICTIONAL WAREHOUSE",),
        )
        warehouse = self.execute(
            'SELECT id FROM "ct_app"."warehouses" WHERE name=%s',
            ("CI FICTIONAL WAREHOUSE",),
        )[0]
        self.execute(
            'INSERT INTO "ct_app"."cash_accounts" (name,currency,balance) '
            'VALUES (%s,%s,%s)',
            ("CI FICTIONAL BANK", "EUR", Decimal("2000")),
        )
        bank = self.execute(
            'SELECT id FROM "ct_app"."cash_accounts" WHERE name=%s',
            ("CI FICTIONAL BANK",),
        )[0]
        po = create_purchase_order(
            self.url, "PURCHASING", "CI-PO-001", "CI FAKE SUPPLIER",
            product[1], warehouse, "1000", "2.25", "EUR"
        )
        self.assertEqual(po[0], "ok", po[0])
        self.assertEqual(
            create_purchase_order(
                self.url, "ADMIN", "CI-PO-001", "CI FAKE SUPPLIER",
                product[1], warehouse, 1000, 2.25, "EUR"
            )[0],
            "duplicate_po",
        )
        shipment = create_shipment(
            self.url, "PURCHASING", po[1], "CI-SHIP-001", 600
        )
        self.assertEqual(shipment[0], "ok", shipment[0])
        self.assertEqual(
            create_shipment(self.url, "PURCHASING", po[1], "CI-OVER", 500)[0],
            "over_shipment",
        )
        receipt = receive_shipment(self.url, "PURCHASING", shipment[1])
        self.assertEqual(receipt[0], "ok", receipt[0])
        self.assertEqual(
            receive_shipment(self.url, "PURCHASING", shipment[1])[0],
            "already_received_or_cancelled",
        )
        hold = hold_inventory_lot(
            self.url, "QUALITY", receipt[1], "CI-QA-001", 100,
            "Synthetic lot hold for isolated CI"
        )
        self.assertEqual(hold[0], "ok", hold[0])
        payable = create_payable(
            self.url, "FINANCE", "CI FAKE SUPPLIER", po[1],
            "CI-INV-001", "2026-12-01", 1350, "EUR"
        )
        self.assertEqual(payable[0], "ok", payable[0])
        self.assertEqual(
            pay_supplier(
                self.url, "FINANCE", payable[1], bank, 500,
                "CI-WIRE-001", "2026-10-10"
            )[0],
            "quality_hold_blocks_payment",
        )
        # Release must close its own quality case atomically.
        self.assertEqual(
            release_inventory_lot(
                self.url, "QUALITY", receipt[1], "CI fictional test resolved"
            )[0],
            "ok",
        )
        self.assertEqual(
            release_inventory_lot(
                self.url, "QUALITY", receipt[1], "Repeat release"
            )[0],
            "lot_not_on_hold",
        )
        self.assertEqual(
            self.execute(
                'SELECT status FROM "ct_app"."quality_cases" WHERE id=%s',
                (hold[1],),
            )[0],
            "Kapandı",
        )
        self.assertEqual(
            pay_supplier(
                self.url, "FINANCE", payable[1], bank, 500,
                "CI-WIRE-001", "2026-10-10"
            )[0],
            "ok",
        )
        self.assertEqual(
            pay_supplier(
                self.url, "FINANCE", payable[1], bank, 100,
                "CI-WIRE-001", "2026-10-10"
            )[0],
            "duplicate_payment",
        )
        # A bank reference must not be reused for another invoice.
        another = create_payable(
            self.url, "FINANCE", "CI FAKE SUPPLIER", po[1],
            "CI-INV-002", "2026-12-15", 100, "EUR"
        )
        self.assertEqual(another[0], "ok")
        self.assertEqual(
            pay_supplier(
                self.url, "FINANCE", another[1], bank, 100,
                "CI-WIRE-001", "2026-10-10"
            )[0],
            "duplicate_payment",
        )
        self.assertEqual(
            pay_supplier(
                self.url, "FINANCE", payable[1], bank, 850,
                "CI-WIRE-002", "2026-10-10"
            )[0],
            "ok",
        )
        self.assertEqual(
            self.execute('SELECT paid_amount FROM "ct_app"."payables" WHERE id=%s',
                         (payable[1],))[0],
            1350,
        )
        self.assertEqual(
            self.execute('SELECT balance FROM "ct_app"."cash_accounts" WHERE id=%s',
                         (bank,))[0],
            650,
        )
        status, counts = read_operational_counts(self.url)
        self.assertEqual(status, "ok", status)
        self.assertEqual(counts["customers"], 1)
        self.assertEqual(counts["inventory_lots"], 1)
        self.assertEqual(counts["quality_cases"], 1)
        self.assertEqual(counts["finance_transactions"], 2)


if __name__ == "__main__":
    unittest.main()
