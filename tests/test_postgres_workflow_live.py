"""Real local PostgreSQL service tests, explicitly skipped without the dedicated DSN."""
import os
from concurrent.futures import ThreadPoolExecutor
from datetime import date

import pytest
import psycopg
import control_tower as ct
import integrated_workflow as flow
import workflow_adjustments as adj
from scripts.build_pg_schema import generate
from scripts.postgres_workflow import Connection,query_df,validate_test_url

URL=os.environ.get('AS_CT_TEST_POSTGRES_URL','')
pytestmark=pytest.mark.skipif(not URL,reason='Dedicated local PostgreSQL service not configured')


@pytest.fixture
def pg_order(monkeypatch):
    validate_test_url(URL)
    with psycopg.connect(URL,autocommit=True) as conn:
        conn.execute('DROP SCHEMA IF EXISTS ct_staging CASCADE')
        conn.execute(generate()[0])
    monkeypatch.setattr(ct,'get_conn',lambda:Connection(URL))
    monkeypatch.setattr(ct,'query_df',lambda sql,params=():query_df(URL,sql,params))
    monkeypatch.setattr(ct,'audit_sql_write',lambda *args:None)
    with ct.get_conn() as c:
        c.execute("INSERT INTO customers (name) VALUES ('Postgres Test Customer')")
        c.execute("INSERT INTO product_catalog (name,supplier,active) VALUES ('PG Ingredient','PG Factory',1)")
        c.execute("INSERT INTO warehouses (name) VALUES ('PG Test Warehouse')")
        c.execute("INSERT INTO opportunities (customer_id,product,stage) VALUES (1,'PG Ingredient','Teklif')")
        c.execute("INSERT INTO quotes (customer_id,opportunity_id,product_name,quantity_kg,buy_price_per_kg,sell_price_per_kg,total_cost_per_kg,customer_credit_days,status) VALUES (1,1,'PG Ingredient',1000,2,3,2.5,90,'Kabul')")
        c.execute("INSERT INTO cash_accounts (name,balance) VALUES ('PG Test EUR',10000)")
    assert flow.create_order(1,1,'PG Factory',1,'PG-PO',date.today())[0]
    with ct.get_conn() as c:
        c.execute("INSERT INTO shipments (purchase_order_id,shipment_ref,quantity_kg,destination_warehouse_id,lot_number) VALUES (1,'PG-SHIP',1000,1,'PG-LOT')")
    return 1


def scalar(sql):
    with ct.get_conn() as c:
        return c.execute(sql).fetchone()[0]


def test_postgres_quote_to_cash_return_and_actual_cost(pg_order):
    assert ct.receive_shipment_to_stock(1)[0]
    assert not ct.receive_shipment_to_stock(1)[0]
    assert ct.set_lot_quality_status(1,'HOLD',hold_kg=100)[0]
    assert not flow.deliver(1,1,400,'PG-INV',date.today())[0]
    assert ct.set_lot_quality_status(1,'Released')[0]
    assert flow.deliver(1,1,400,'PG-INV',date.today())[0]
    assert ct.record_receivable_payment(1,1200,date.today(),1,'PG-REC','')[0]
    assert adj.return_delivery(1,100,'PG-RETURN',date.today(),'Test')[0]
    assert scalar('SELECT amount FROM payables WHERE id=2')==300
    assert ct.record_payable_payment(2,300,date.today(),1,'PG-REFUND','')[0]
    assert scalar('SELECT balance FROM cash_accounts')==10900
    assert ct.outstanding_receivables().empty
    assert flow.overview().iloc[0]['sevk_kg']==300
    assert adj.add_cost(1,'PG-GOODS','Mal bedeli',2000,'EUR',1,date.today(),'Test')[0]
    assert adj.add_cost(1,'PG-FREIGHT','Navlun',100,'EUR',1,date.today(),'Test')[0]
    assert adj.reconcile(1,True,'Complete')[0]
    assert adj.cost_report().iloc[0]['gerçekleşen_katkı']==pytest.approx(270)
    with pytest.raises(psycopg.Error):
        with ct.get_conn() as c:
            c.execute('UPDATE quotes SET quantity_kg=500 WHERE id=1')


def test_postgres_concurrent_receive_payment_and_reversal(pg_order):
    with ThreadPoolExecutor(max_workers=2) as pool:
        received=list(pool.map(ct.receive_shipment_to_stock,[1,1]))
    assert sum(ok for ok,_ in received)==1
    assert scalar('SELECT COUNT(*) FROM inventory_lots')==1
    with ThreadPoolExecutor(max_workers=2) as pool:
        paid=list(pool.map(lambda ref:ct.record_payable_payment(1,1500,date.today(),1,ref,''),['PG-P1','PG-P2']))
    assert sum(ok for ok,_ in paid)==1
    assert adj.reverse_payment(1,'PG-UNDO','Mistake')[0]
    assert scalar('SELECT balance FROM cash_accounts')==10000
    assert scalar('SELECT paid_amount FROM payables')==0


def test_postgres_delivery_failure_rolls_back(pg_order):
    assert ct.receive_shipment_to_stock(1)[0]
    with ct.get_conn() as c:
        c.execute("""CREATE FUNCTION ct_staging.reject_stock() RETURNS trigger LANGUAGE plpgsql AS $$
            BEGIN RAISE EXCEPTION 'forced test rollback'; END; $$""")
        c.execute('CREATE TRIGGER reject_stock BEFORE UPDATE ON inventory_lots FOR EACH ROW EXECUTE FUNCTION ct_staging.reject_stock()')
    with pytest.raises(psycopg.Error):
        flow.deliver(1,1,100,'PG-FAIL',date.today())
    assert scalar('SELECT COUNT(*) FROM receivables')==0
    assert scalar('SELECT COUNT(*) FROM workflow_deliveries')==0


def test_postgres_multi_line_batch_and_rollback(pg_order):
    with ct.get_conn() as c:
        c.execute("INSERT INTO quotes (customer_id,product_name,quantity_kg,buy_price_per_kg,sell_price_per_kg,total_cost_per_kg,status) VALUES (1,'PG Ingredient',100,2,3,2.5,'Kabul')")
        c.execute("INSERT INTO product_catalog (name,active) VALUES ('Second PG Ingredient',1)")
        c.execute("INSERT INTO quotes (customer_id,product_name,quantity_kg,buy_price_per_kg,sell_price_per_kg,total_cost_per_kg,status) VALUES (1,'Second PG Ingredient',200,4,6,5,'Taslak')")
    assert not flow.create_order_batch([2,3],'PG Factory',1,'PG-GROUP',date.today())[0]
    assert scalar('SELECT COUNT(*) FROM workflow_order_groups')==0
    assert scalar('SELECT COUNT(*) FROM purchase_orders')==1
    with ct.get_conn() as c:
        c.execute("UPDATE quotes SET status='Kabul' WHERE id=3")
    assert flow.create_order_batch([2,3],'PG Factory',1,'PG-GROUP',date.today())[0]
    assert scalar('SELECT COUNT(*) FROM workflow_group_lines')==2


def test_additive_workflow_migration_is_repeatable_and_preserves_data():
    from scripts.build_workflow_migration import generate_migration
    validate_test_url(URL)
    with psycopg.connect(URL,autocommit=True) as conn:
        conn.execute('DROP SCHEMA IF EXISTS ct_staging CASCADE')
        conn.execute(generate()[0])
        conn.execute("INSERT INTO ct_staging.customers (name) VALUES ('Keep this synthetic customer')")
        conn.execute('ALTER TABLE ct_staging.receivables DROP COLUMN credit_amount')
        # Simulate the pre-workflow schema without modifying any external DB.
        tables=conn.execute("SELECT tablename FROM pg_tables WHERE schemaname='ct_staging' AND (tablename LIKE 'workflow_%' OR tablename='finance_reversals')").fetchall()
        for (table,) in tables:
            from psycopg import sql
            conn.execute(sql.SQL('DROP TABLE IF EXISTS ct_staging.{} CASCADE').format(sql.Identifier(table)))
        conn.execute(generate_migration())
        conn.execute(generate_migration())
        assert conn.execute('SELECT name FROM ct_staging.customers').fetchone()[0]=='Keep this synthetic customer'
        assert conn.execute("SELECT COUNT(*) FROM information_schema.columns WHERE table_schema='ct_staging' AND table_name='receivables' AND column_name='credit_amount'").fetchone()[0]==1
