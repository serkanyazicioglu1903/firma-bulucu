"""Offline transaction and guard tests for Stage 7 PostgreSQL operations."""
from copy import deepcopy
import re
import sys
import types
import unittest
from unittest.mock import patch

from scripts.staging_ops_adapter import (
    PREFIX, PilotSafetyError, create_ops_pilot, advance_ops_pilot,
    delete_ops_pilot, list_ops_pilots, names
)


class Store:
    def __init__(self):
        self.tables={name:{} for name in (
            "product_catalog","warehouses","purchase_orders","shipments",
            "payables","cash_accounts","inventory_lots","quality_cases",
            "finance_transactions")}
        self.fail_sql=None
        self.rollbacks=0
        self.commits=0
        self.statements=[]


class Transaction:
    def __init__(self,store):
        self.store=store
    def __enter__(self):
        self.previous=deepcopy(self.store.tables)
        return self
    def __exit__(self, exc_type, *_):
        if exc_type:
            self.store.tables=self.previous
            self.store.rollbacks+=1
        else:
            self.store.commits+=1
        return False


class Connection:
    def __init__(self,store):
        self.store=store
    def __enter__(self):
        return self
    def __exit__(self,*_):
        return False
    def transaction(self):
        return Transaction(self.store)
    def cursor(self):
        return Cursor(self.store)


class Cursor:
    def __init__(self, store):
        self.store=store
        self.answer=None
        self.rows=[]
    def __enter__(self):
        return self
    def __exit__(self,*_):
        return False
    def fetchone(self):
        return self.answer
    def fetchall(self):
        return self.rows

    def execute(self, sql, params=()):
        self.store.statements.append((sql,params))
        self.answer=None
        self.rows=[]
        if self.store.fail_sql and self.store.fail_sql in sql:
            raise RuntimeError("password=redactedsecret should never be leaked")
        if sql.startswith("SET "):
            return
        hit=re.search(r'"ct_staging"\."([a-z_]+)"',sql)
        if not hit:
            raise AssertionError("Queries must address ct_staging explicitly.")
        table=hit.group(1)
        tables=self.store.tables
        if sql.startswith("INSERT INTO"):
            ident=params[0]
            if ident in tables[table]:
                raise RuntimeError("Duplicate synthetic ID")
            n=names(ident)
            expected={
                "product_catalog":n["PRODUCT"],"warehouses":n["WAREHOUSE"],
                "purchase_orders":n["PO"],"shipments":n["SHIPMENT"],
                "payables":n["SUPPLIER"],"cash_accounts":n["BANK"],
                "quality_cases":n["QUALITY"]}
            if table in expected:
                self.assert_marker(expected[table],params)
            entry={"marker":expected.get(table),"id":ident}
            if table=="shipments":entry["received"]=0
            if table=="payables":entry["paid"]=0.0
            if table=="cash_accounts":entry["balance"]=10000.0
            if table=="inventory_lots":entry["available"]=600.0;entry["hold"]=0.0
            tables[table][ident]=entry
            return
        if sql.startswith("SELECT po.quantity_kg"):
            ident=params[0]
            n=names(ident)
            if (ident in tables["purchase_orders"]
                    and ident in tables["shipments"]
                    and ident in tables["payables"]
                    and ident in tables["cash_accounts"]
                    and ident in tables["product_catalog"]
                    and ident in tables["warehouses"]
                    and tuple(params[1:]) == (
                        n["PO"],n["SUPPLIER"],n["PRODUCT"],n["PRODUCT"],
                        n["WAREHOUSE"],n["SHIPMENT"],n["SUPPLIER"],n["BANK"])):
                self.answer=(1000.0,600.0,
                             tables["shipments"][ident]["received"],
                             2250.0,tables["payables"][ident]["paid"],
                             tables["cash_accounts"][ident]["balance"])
            return
        if sql.startswith("SELECT l.quantity_received_kg"):
            ident=params[0]
            lot=tables["inventory_lots"].get(ident)
            if lot:
                quality=tables["quality_cases"].get(ident)
                finance=tables["finance_transactions"].get(ident)
                self.answer=(600.0,lot["available"],lot["hold"],
                             "HOLD" if lot["hold"] else "Released",
                             ident if quality else None,
                             ident if finance else None,
                             500.0 if finance else None)
            return
        if sql.startswith("SELECT po.id"):
            for ident in tables["purchase_orders"]:
                lot=tables["inventory_lots"].get(ident)
                quality=tables["quality_cases"].get(ident)
                finance=tables["finance_transactions"].get(ident)
                self.rows.append((
                    ident,tables["shipments"][ident]["received"],
                    600.0 if lot else None,
                    lot["available"] if lot else None,
                    lot["hold"] if lot else None,
                    ident if quality else None,2250.0,
                    tables["payables"][ident]["paid"],
                    tables["cash_accounts"][ident]["balance"],
                    ident if finance else None
                ))
            return
        if sql.startswith('SELECT id FROM "ct_staging"."inventory_lots"') and "quality_status=%s" in sql:
            ident=params[0]
            lot=tables["inventory_lots"].get(ident)
            self.answer=(ident,) if lot and lot["hold"]==100.0 and lot["available"]==600.0 else None
            return
        if sql.startswith("SELECT id FROM"):
            ident=params[0]
            self.answer=(ident,) if ident in tables[table] else None
            return
        if sql.startswith("SELECT 1 FROM"):
            ident=params[0]
            self.answer=(1,) if ident in tables[table] else None
            return
        if sql.startswith("UPDATE "):
            ident=params[-1] if table=="shipments" else (
                params[2] if table=="inventory_lots" else
                params[2] if table=="payables" else params[1])
            row=tables[table].get(ident)
            if table=="shipments" and row and row["received"]==0:
                row["received"]=1;self.answer=(ident,)
            if table=="inventory_lots" and row and row["hold"]==0:
                row["hold"]=100.0;self.answer=(ident,)
            if table=="payables" and row and row["paid"]==0:
                row["paid"]=500.0;self.answer=(ident,)
            if table=="cash_accounts" and row and row["balance"]>=500:
                row["balance"]-=500;self.answer=(ident,)
            return
        if sql.startswith("DELETE FROM"):
            ident=params[0]
            # The real SQL has exact per-table ownership predicates.
            if "WHERE id=%s" not in sql:
                raise AssertionError("Unsafe deletion without scoped id")
            if ident in tables[table]:
                del tables[table][ident]
                self.answer=(ident,)
            return
        raise AssertionError("Unexpected SQL type: " + sql[:120])

    @staticmethod
    def assert_marker(marker,params):
        if marker not in params:
            raise AssertionError("Missing fictional identifier guard")


class OperationsPilotTests(unittest.TestCase):
    dsn="postgresql://test:secret@localhost/staging"
    def setUp(self):
        self.store=Store()
        fake=types.SimpleNamespace(
            connect=lambda *_args,**_kwargs:Connection(self.store))
        self.mockpg=patch.dict(sys.modules,{"psycopg":fake})
        self.mockval=patch(
            "scripts.staging_ops_adapter.validate_staging_structure",
            return_value=("ok",[]))
        self.mockpg.start();self.mockval.start()
        self.addCleanup(self.mockpg.stop);self.addCleanup(self.mockval.stop)

    def create(self):
        state,ident=create_ops_pilot(self.dsn)
        self.assertEqual(state,"created")
        return ident

    def test_persistent_lifecycle_and_exact_numeric_reconciliation(self):
        ident=self.create()
        result,rows=list_ops_pilots(self.dsn)
        self.assertEqual(result,"ok")
        self.assertEqual(rows[0]["stage"],"Sipariş")
        self.assertEqual(advance_ops_pilot(self.dsn,ident,"receive"),"updated")
        self.assertEqual(list_ops_pilots(self.dsn)[1][0]["received_kg"],600)
        self.assertEqual(advance_ops_pilot(self.dsn,ident,"hold"),"updated")
        self.assertEqual(list_ops_pilots(self.dsn)[1][0]["available_kg"],500)
        self.assertEqual(list_ops_pilots(self.dsn)[1][0]["remaining_kg"],400)
        self.assertEqual(advance_ops_pilot(self.dsn,ident,"pay"),"updated")
        stage=list_ops_pilots(self.dsn)[1][0]
        self.assertEqual(stage["stage"],"Ödeme")
        self.assertEqual(stage["payable_eur"],1750)
        self.assertEqual(stage["bank_eur"],9500)
        self.assertEqual(delete_ops_pilot(self.dsn,ident),"deleted")
        self.assertEqual(list_ops_pilots(self.dsn),("ok",[]))
        self.assertTrue(all(not data for data in self.store.tables.values()))

    def test_payment_before_receive_or_hold_is_refused(self):
        ident=self.create()
        self.assertEqual(advance_ops_pilot(self.dsn,ident,"pay"),"not_ready")
        self.assertEqual(advance_ops_pilot(self.dsn,ident,"hold"),"not_ready")
        self.assertEqual(advance_ops_pilot(self.dsn,ident,"receive"),"updated")
        self.assertEqual(advance_ops_pilot(self.dsn,ident,"receive"),"not_ready")
        self.assertEqual(advance_ops_pilot(self.dsn,ident,"pay"),"not_ready")
        self.assertEqual(self.store.tables["payables"][ident]["paid"],0)

    def test_payment_rejects_missing_or_changed_hold(self):
        ident=self.create()
        self.assertEqual(advance_ops_pilot(self.dsn,ident,"receive"),"updated")
        self.assertEqual(advance_ops_pilot(self.dsn,ident,"hold"),"updated")
        self.store.tables["inventory_lots"][ident]["hold"]=0.0
        self.assertEqual(advance_ops_pilot(self.dsn,ident,"pay"),"not_ready")
        self.assertEqual(self.store.tables["payables"][ident]["paid"],0)
        self.assertEqual(self.store.tables["cash_accounts"][ident]["balance"],10000)

    def test_failure_rolling_back_payment_and_cash(self):
        ident=self.create()
        self.assertEqual(advance_ops_pilot(self.dsn,ident,"receive"),"updated")
        self.assertEqual(advance_ops_pilot(self.dsn,ident,"hold"),"updated")
        self.store.fail_sql='INSERT INTO "ct_staging"."finance_transactions"'
        self.assertEqual(advance_ops_pilot(self.dsn,ident,"pay"),"failed")
        self.assertEqual(self.store.tables["payables"][ident]["paid"],0)
        self.assertEqual(self.store.tables["cash_accounts"][ident]["balance"],10000)
        self.assertGreater(self.store.rollbacks,0)

    def test_unrelated_record_cannot_be_deleted(self):
        ident=self.create()
        wrong=ident-1
        self.store.tables["purchase_orders"][wrong]={"marker":"REAL"}
        self.assertEqual(delete_ops_pilot(self.dsn,wrong),"not_ready")
        self.assertIn(wrong,self.store.tables["purchase_orders"])
        self.assertIn(ident,self.store.tables["purchase_orders"])

    def test_cleanup_refuses_divergent_hold_without_deleting(self):
        ident=self.create()
        self.assertEqual(advance_ops_pilot(self.dsn,ident,"receive"),"updated")
        self.assertEqual(advance_ops_pilot(self.dsn,ident,"hold"),"updated")
        self.store.tables["inventory_lots"][ident]["hold"]=50.0
        before=deepcopy(self.store.tables)
        self.assertEqual(delete_ops_pilot(self.dsn,ident),"not_ready")
        self.assertEqual(self.store.tables,before)

    def test_schema_failure_does_not_write(self):
        with patch("scripts.staging_ops_adapter.validate_staging_structure",
                   return_value=("mismatch",[])):
            self.assertEqual(create_ops_pilot(self.dsn),("not_ready",None))
        self.assertEqual(self.store.statements,[])

    def test_reject_bad_identifiers_and_unknown_steps(self):
        for ident in (-1,0,1,True,None,"-1001",-(1<<63)):
            with self.subTest(ident=ident):
                with self.assertRaises(PilotSafetyError):
                    names(ident)
        ident=self.create()
        self.assertEqual(advance_ops_pilot(self.dsn,ident,"DROP TABLE"),"not_ready")


if __name__=="__main__":
    unittest.main()
