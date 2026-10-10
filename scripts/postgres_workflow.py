"""Local PostgreSQL staging adapter for real workflow acceptance tests.

Fail closed: only loopback, an explicit AS_CT_TEST_POSTGRES_URL argument and the
ct_staging schema are allowed. It does not switch the application's live backend,
read DATABASE_URL, or connect to Supabase. SQL is shared with the business services.
"""
import re
import pandas as pd
import psycopg
from psycopg.conninfo import conninfo_to_dict

IDENTITY_TABLES = {
    'customers','product_catalog','warehouses','opportunities','quotes','purchase_orders',
    'payables','receivables','inventory_lots','shipments','cash_accounts','finance_transactions',
    'audit_log','workflow_orders','workflow_deliveries','workflow_costs','workflow_returns',
    'finance_reversals','workflow_order_groups','workflow_group_lines','regulatory_items','quality_cases','tasks',
}


def validate_test_url(url):
    cfg=conninfo_to_dict(url)
    if cfg.get('host') not in ('127.0.0.1','localhost','::1') or cfg.get('hostaddr'):
        raise ValueError('Only explicit loopback PostgreSQL test instances are allowed.')
    if cfg.get('dbname') != 'ct_test':
        raise ValueError('Only the dedicated ct_test database is allowed.')
    if cfg.get('options') or cfg.get('service'):
        raise ValueError('Connection search_path/options overrides are not allowed.')
    return url


class Row(dict):
    def __getitem__(self, key):
        if isinstance(key,int):
            return tuple(self.values())[key]
        return super().__getitem__(key)


def row_factory(cursor):
    names=[col.name for col in cursor.description] if cursor.description else []
    return lambda values:Row(zip(names,values))


def sql_for_pg(sql):
    # Business services pass values separately. No user text is interpolated.
    return sql.replace('?', '%s')


class Cursor:
    def __init__(self,cursor,lastrowid=None):
        self.cursor=cursor
        self.lastrowid=lastrowid
    def fetchone(self):
        return self.cursor.fetchone()
    def fetchall(self):
        return self.cursor.fetchall()
    @property
    def rowcount(self):
        return self.cursor.rowcount


class Connection:
    def __init__(self,url):
        self.conn=psycopg.connect(validate_test_url(url),row_factory=row_factory,connect_timeout=5)
    def __enter__(self):
        self.conn.execute('SET LOCAL search_path TO ct_staging')
        self.conn.execute("SET LOCAL lock_timeout TO '10s'")
        self.conn.execute("SET LOCAL statement_timeout TO '20s'")
        return self
    def __exit__(self,kind,value,tb):
        try:
            self.conn.rollback() if kind else self.conn.commit()
        finally:
            self.conn.close()
    def execute(self,sql,params=()):
        if sql.strip().upper()=='BEGIN IMMEDIATE':
            # Same isolation contract as SQLite BEGIN IMMEDIATE. A dedicated
            # transaction advisory lock serializes the pilot write services.
            return Cursor(self.conn.execute('SELECT pg_advisory_xact_lock(26061028)'))
        sql=sql_for_pg(sql)
        match=re.match(r'\s*INSERT\s+INTO\s+([a-z_]+)',sql,re.I)
        returning=bool(match and match.group(1) in IDENTITY_TABLES and 'RETURNING' not in sql.upper())
        if returning:
            sql=sql.rstrip().rstrip(';')+' RETURNING id'
        cur=self.conn.execute(sql,tuple(x.item() if hasattr(x,'item') else x for x in params))
        return Cursor(cur,cur.fetchone()['id'] if returning else None)
    def commit(self):
        self.conn.commit()
    def rollback(self):
        self.conn.rollback()


def query_df(url,sql,params=()):
    with Connection(url) as conn:
        cur=conn.execute(sql,params).cursor
        columns=[col.name for col in cur.description]
        return pd.DataFrame([dict(row) for row in cur.fetchall()],columns=columns)
