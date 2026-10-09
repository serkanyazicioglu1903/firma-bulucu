"""Offline transactional tests for the isolated, persistent PostgreSQL CRM pilot."""
from copy import deepcopy
import sys
import types
import unittest
from unittest.mock import patch

from scripts.staging_crm_adapter import (
    _marker, SandboxError, create_sandbox_crm,
    list_sandbox_crm, update_sandbox_crm, delete_sandbox_crm,
)


class FakeStore:
    def __init__(self):
        self.rows={t:{} for t in ("customers","product_catalog","opportunities","tasks")}
        self.statements=[]
        self.rollbacks=0
        self.commits=0
        self.fail_task_update=False


class FakeTransaction:
    def __init__(self, store):
        self.store=store
    def __enter__(self):
        self.before=deepcopy(self.store.rows)
        return self
    def __exit__(self, exc_type, *_):
        if exc_type is None:
            self.store.commits+=1
        else:
            self.store.rows=self.before
            self.store.rollbacks+=1
        return False


class FakeConnection:
    def __init__(self, store):
        self.store=store
    def __enter__(self):
        return self
    def __exit__(self, *_):
        return False
    def transaction(self):
        return FakeTransaction(self.store)
    def cursor(self):
        return FakeCursor(self.store)


class FakeCursor:
    def __init__(self, store):
        self.store=store
        self.rowcount=0
        self.return_row=None
        self.return_rows=[]
    def __enter__(self):
        return self
    def __exit__(self, *_):
        return False

    def execute(self, sql, params=()):
        self.store.statements.append((sql,params))
        self.rowcount=0
        self.return_row=None
        self.return_rows=[]
        if sql.startswith(("SET ",)):
            return
        if sql.startswith("SELECT c.id"):
            rows=[]
            for ident, c in self.store.rows["customers"].items():
                p=self.store.rows["product_catalog"].get(ident)
                o=self.store.rows["opportunities"].get(ident)
                t=self.store.rows["tasks"].get(ident)
                if p and o and t and c["name"].startswith("CT_SANDBOX_"):
                    rows.append((ident,c["name"],p["name"],o["stage"],t["status"]))
            self.return_rows=sorted(rows)[:50]
            return
        if sql.startswith("SELECT id FROM"):
            ident,name=params
            row=self.store.rows["customers"].get(ident)
            self.return_row=(ident,) if row and row["name"] == name else None
            return
        if sql.startswith(("INSERT ","UPDATE ","DELETE ")):
            if '"ct_staging".' not in sql:
                raise AssertionError("Write outside ct_staging")
            for table in self.store.rows:
                if f'"ct_staging"."{table}"' in sql:
                    break
            else:
                raise AssertionError("Unknown table")
            rows=self.store.rows[table]
            if sql.startswith("INSERT "):
                ident=params[0]
                if ident in rows:
                    raise RuntimeError("Unique collision")
                if table=="customers": rows[ident]={"name":params[1]}
                elif table=="product_catalog": rows[ident]={"name":params[1]}
                elif table=="opportunities":
                    rows[ident]={"customer_id":params[1],"product":params[2],"stage":params[3]}
                elif table=="tasks":
                    rows[ident]={"title":params[1],"status":params[2]}
                self.rowcount=1
                return
            if sql.startswith("UPDATE "):
                if table=="tasks" and self.store.fail_task_update:
                    raise RuntimeError("password=SECRET in fake PG")
                ident=params[1]
                row=rows.get(ident)
                if table=="opportunities" and row and row["customer_id"]==params[2] \
                   and row["product"]==params[3] and row["stage"]==params[4]:
                    row["stage"]=params[0]; self.rowcount=1
                elif table=="tasks" and row and row["title"]==params[2] \
                     and row["status"]==params[3]:
                    row["status"]=params[0];self.rowcount=1
                return
            if sql.startswith("DELETE "):
                ident=params[0]
                row=rows.get(ident)
                good=False
                if row:
                    if table=="tasks":good=row["title"]==params[1]
                    elif table=="opportunities":
                        good=row["customer_id"]==params[1] and row["product"]==params[2]
                    else:good=row["name"]==params[1]
                if good:
                    del rows[ident]
                    self.rowcount=1
                return
        raise AssertionError("Unexpected SQL " + sql)

    def fetchone(self):
        return self.return_row
    def fetchall(self):
        return self.return_rows


class CrmPilotTests(unittest.TestCase):
    url="postgresql://fictional:password@localhost/staging"

    def setUp(self):
        self.store=FakeStore()
        fake=types.SimpleNamespace(connect=lambda *a,**kw:FakeConnection(self.store))
        self.modules=patch.dict(sys.modules,{"psycopg":fake})
        self.validation=patch("scripts.staging_crm_adapter.validate_staging_structure",
                              return_value=("ok",[]))
        self.modules.start()
        self.validation.start()
        self.addCleanup(self.modules.stop)
        self.addCleanup(self.validation.stop)

    def test_create_read_update_delete_with_persistence(self):
        status,ident=create_sandbox_crm(self.url)
        self.assertEqual(status,"created")
        self.assertLess(ident, -1000)
        status,rows=list_sandbox_crm(self.url)
        self.assertEqual(status,"ok")
        self.assertEqual(len(rows),1)
        self.assertEqual(rows[0]["stage"],"Lead")
        self.assertEqual(update_sandbox_crm(self.url,ident),"updated")
        _,rows=list_sandbox_crm(self.url)
        self.assertEqual(rows[0]["stage"],"Numune")
        self.assertEqual(rows[0]["task_status"],"Tamamlandı")
        self.assertEqual(delete_sandbox_crm(self.url,ident),"deleted")
        _,rows=list_sandbox_crm(self.url)
        self.assertEqual(rows,[])
        self.assertEqual(sum(map(len,self.store.rows.values())),0)
        self.assertEqual(self.store.rollbacks,0)

    def test_failed_task_update_rolls_back_opportunity_change(self):
        _,ident=create_sandbox_crm(self.url)
        self.store.fail_task_update=True
        self.assertEqual(update_sandbox_crm(self.url,ident),"failed")
        self.assertEqual(self.store.rows["opportunities"][ident]["stage"],"Lead")
        self.assertEqual(self.store.rollbacks,1)

    def test_never_delete_unrelated_rows(self):
        _,ident=create_sandbox_crm(self.url)
        another=ident-1
        self.store.rows["customers"][another]={"name":"REAL_CUSTOMER"}
        self.assertEqual(delete_sandbox_crm(self.url,another),"not_ready")
        self.assertIn(another,self.store.rows["customers"])
        self.assertIn(ident,self.store.rows["customers"])

    def test_no_write_when_schema_missing(self):
        with patch("scripts.staging_crm_adapter.validate_staging_structure",
                   return_value=("mismatch",[])):
            self.assertEqual(create_sandbox_crm(self.url),("not_ready",None))
            self.assertFalse(self.store.statements)

    def test_reject_bad_ids(self):
        for ident in (-1,0,1,None,True,"-2000", -(1<<63)):
            with self.subTest(ident=ident):
                with self.assertRaises(SandboxError):
                    _marker(ident)


if __name__=="__main__":
    unittest.main()
