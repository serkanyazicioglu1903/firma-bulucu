"""Offline validations for PostgreSQL rollback business pilot."""
import sys
import types
import unittest
from unittest.mock import patch

from scripts.staging_business_pilot import (
    BusinessRuleError, TEST_TABLES, quote_preview,
    stock_after_receipt, settle_invoice, run_staging_business_pilot
)


class MockCursor:
    def __init__(self, conn):
        self.conn = conn
        self.sql = ""
        self.rowcount = 1

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False

    def execute(self, sql, params=()):
        self.sql = sql
        self.conn.statements.append((sql, params, self.conn.in_transaction))
        if sql.startswith(("INSERT ", "UPDATE ", "DELETE ")) and not self.conn.in_transaction:
            raise AssertionError("SQL write outside forced-rollback transaction")
        if sql.startswith(("INSERT ", "UPDATE ", "DELETE ")):
            self.assert_schema(sql)
        if self.conn.fail_on and self.conn.fail_on in sql:
            raise RuntimeError("postgres://secret-password@host/private")
        self.rowcount = 1

    @staticmethod
    def assert_schema(sql):
        if '"ct_staging".' not in sql or "public." in sql:
            raise AssertionError("Write outside ct_staging")

    def fetchone(self):
        sql = self.sql
        if sql.startswith("SELECT q.profit_total_base"):
            from scripts.staging_business_pilot import quote_preview
            amount = quote_preview(1000,2.2,.92,450,3.1,10,90,1)["profit_eur_total"]
            marker = next(v[1][1].removesuffix("_CUSTOMER")
                          for v in self.conn.statements
                          if v[0].startswith('INSERT INTO "ct_staging"."customers"'))
            return (amount, marker+"_CUSTOMER")
        if sql.startswith("SELECT l.quantity_received_kg"):
            return (600.0, 600.0, 100.0, 1)
        if sql.startswith("SELECT r.amount-r.paid_amount"):
            return (1800.0, 1400.0, 0.92, 1300.0)
        if sql.startswith('SELECT 1 FROM "ct_staging"'):
            if not self.conn.rolled_back:
                raise AssertionError("Post-rollback verification ran too early")
            return None
        raise AssertionError("Unexpected SELECT in pilot: " + sql[:120])


class MockTransaction:
    def __init__(self, conn):
        self.conn=conn

    def __enter__(self):
        self.conn.in_transaction=True
        return self

    def __exit__(self, exc_type, _exc, _trace):
        self.conn.in_transaction=False
        self.conn.rolled_back=(exc_type is not None)
        return False


class MockConnection:
    def __init__(self, fail_on=None):
        self.in_transaction=False
        self.rolled_back=False
        self.statements=[]
        self.fail_on=fail_on

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False

    def cursor(self):
        return MockCursor(self)

    def transaction(self):
        return MockTransaction(self)


class BusinessModelTests(unittest.TestCase):
    def test_quote_with_fx_and_financing(self):
        quote=quote_preview(1000,2.20,0.92,450,3.1,10,90,1)
        landed=2.20*.92+450/1000
        expected_cost=landed*(1+.10*90/365)+3.1*.01
        self.assertAlmostEqual(quote["cost_eur_kg"], expected_cost)
        self.assertAlmostEqual(quote["profit_eur_total"],(3.1-expected_cost)*1000)
        self.assertGreater(quote["margin_pct"], 0)

    def test_quote_rejects_zero_qty_nan_and_negative_fx(self):
        for kwargs in (
            (0,2,.92,0,3,10,90,0),
            (1000,2,float("nan"),0,3,10,90,0),
            (1000,2,-1,0,3,10,90,0),
            (1000,2,.92,0,0,10,90,0),
            (1000,2,.92,0,3,101,90,0),
            (1000,2,.92,0,3,10,-1,0),
        ):
            with self.subTest(kwargs=kwargs), self.assertRaises(BusinessRuleError):
                quote_preview(*kwargs)

    def test_partial_receipt_and_quality_hold(self):
        self.assertEqual(stock_after_receipt(1000,0,600,100),
                         {"received":600.0,"available":500.0,"hold":100.0,
                          "remaining":400.0})
        with self.assertRaises(BusinessRuleError):
            stock_after_receipt(1000,600,500,0)
        with self.assertRaises(BusinessRuleError):
            stock_after_receipt(1000,0,600,650)

    def test_partial_receivable_and_currency_aware_payable(self):
        self.assertEqual(settle_invoice(3100,0,1300,1)["outstanding"],1800)
        self.assertAlmostEqual(settle_invoice(2200,0,800,.92)["outstanding_eur"],1288)
        self.assertEqual(settle_invoice(100,50,50,1)["status"],"Kapandı")
        with self.assertRaises(BusinessRuleError):
            settle_invoice(100,50,51,1)


class TransactionPilotTests(unittest.TestCase):
    def call(self, conn):
        fake=types.SimpleNamespace(connect=lambda *args, **kwargs: conn)
        with patch.dict(sys.modules,{"psycopg":fake}), \
             patch("scripts.staging_business_pilot.validate_staging_structure",
                   return_value=("ok", [])):
            return run_staging_business_pilot("postgresql://user:pass@local/db")

    def test_complete_workflow_is_rolled_back(self):
        conn=MockConnection()
        status, report=self.call(conn)
        self.assertEqual(status, "passed")
        self.assertTrue(conn.rolled_back)
        self.assertEqual(len([sql for sql,_,_ in conn.statements
                              if sql.startswith('SELECT 1 FROM "ct_staging"')]),
                         len(TEST_TABLES))
        self.assertEqual(report["available_kg"],500)
        self.assertEqual(report["remaining_kg"],400)
        self.assertEqual(report["receivable_eur"],1800)
        self.assertEqual(report["payable_eur"],1288)
        self.assertTrue(all(flag for sql,_,flag in conn.statements
                            if sql.startswith(("INSERT ", "UPDATE ", "DELETE "))))

    def test_exception_rolls_back_and_hides_connection_details(self):
        conn=MockConnection(fail_on='INSERT INTO "ct_staging"."payables"')
        status, report=self.call(conn)
        self.assertEqual((status,report), ("failed",{}))
        self.assertTrue(conn.rolled_back)

    def test_schema_validation_prevents_writes(self):
        with patch("scripts.staging_business_pilot.validate_staging_structure",
                   return_value=("mismatch", [])):
            self.assertEqual(run_staging_business_pilot(
                "postgresql://user:pass@local/db"), ("schema_mismatch",{}))

    def test_url_required(self):
        self.assertEqual(run_staging_business_pilot(None),("invalid_url",{}))


if __name__=="__main__":
    unittest.main()
