"""Real local PostgreSQL service tests, explicitly skipped without the dedicated DSN."""
import os
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
from datetime import date

import pytest
import psycopg
import control_tower as ct
import integrated_workflow as flow
import workflow_adjustments as adj
from scripts.build_pg_schema import generate
from scripts.postgres_workflow import validate_test_url

URL=os.environ.get('AS_CT_TEST_POSTGRES_URL','')
pytestmark=pytest.mark.skipif(not URL,reason='Dedicated local PostgreSQL service not configured')


@pytest.fixture
def pg_order(monkeypatch):
    validate_test_url(URL)
    with psycopg.connect(URL,autocommit=True) as conn:
        conn.execute('DROP SCHEMA IF EXISTS ct_staging CASCADE')
        conn.execute(generate()[0])
    monkeypatch.setenv('AS_CONTROL_TOWER_BACKEND', 'postgres')
    monkeypatch.setenv('AS_CONTROL_TOWER_POSTGRES_URL', URL)
    monkeypatch.setenv('AS_CONTROL_TOWER_POSTGRES_SCHEMA', 'ct_staging')
    ct.init_db()
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
        c.conn.execute("""CREATE FUNCTION ct_staging.reject_stock() RETURNS trigger LANGUAGE plpgsql AS $$
            BEGIN RAISE EXCEPTION 'forced test rollback'; END; $$""")
        c.conn.execute('CREATE TRIGGER reject_stock BEFORE UPDATE ON inventory_lots FOR EACH ROW EXECUTE FUNCTION ct_staging.reject_stock()')
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


@pytest.mark.parametrize('role', ['ADMIN','SALES','PURCHASING','FINANCE','QUALITY','VIEWER'])
def test_all_postgres_role_screens(pg_order, role):
    from streamlit.testing.v1 import AppTest
    import security_admin
    assert ct.receive_shipment_to_stock(1)[0]
    assert flow.deliver(1,1,100,'UI-INV',date.today())[0]
    assert adj.add_cost(1,'UI-GOODS','Mal bedeli',2000,'EUR',1,date.today(),'Test')[0]
    # All module tabs execute during the same Streamlit run, including reporting,
    # system admin/export and role-specific portals, without monkeypatched SQL.
    app = AppTest.from_file(Path(__file__).resolve().parents[1]/'app.py', default_timeout=90)
    app.session_state['ct_user'] = {'username':'pg-test','display_name':'PG Test','role':role}
    app.session_state['ct_session_id'] = 'pg-app-test'
    app.run()
    assert not app.exception, [e.message for e in app.exception]
    import zipfile, io
    with zipfile.ZipFile(io.BytesIO(security_admin.export_all_tables_zip(ct.DB_PATH))) as archive:
        assert 'customers.csv' in archive.namelist()
        assert 'Postgres Test Customer' in archive.read('customers.csv').decode()
    # A fresh connection sees the same persistent records, including audit writes.
    assert scalar('SELECT COUNT(*) FROM audit_log') > 0


def test_empty_postgres_application(pg_order):
    from streamlit.testing.v1 import AppTest
    with psycopg.connect(URL,autocommit=True) as conn:
        conn.execute('DROP SCHEMA ct_staging CASCADE')
        conn.execute(generate()[0])
    app = AppTest.from_file(Path(__file__).resolve().parents[1]/'app.py',default_timeout=90)
    app.session_state['ct_user'] = {'username':'pg-test','display_name':'PG Test','role':'ADMIN'}
    app.run()
    assert not app.exception, [e.message for e in app.exception]
    assert scalar('SELECT COUNT(*) FROM customers') == 0
    assert scalar('SELECT COUNT(*) FROM product_catalog') == 0


def test_postgres_dates_literals_and_connection_reuse(pg_order):
    with ct.get_conn() as conn:
        row = conn.execute("SELECT '?' AS literal, ? AS bound, julianday('invalid') AS bad, julianday('') AS blank, julianday('2026-10-10')-julianday('2026-10-09') AS days", ('100% ?',)).fetchone()
        assert row['literal'] == '?' and row['bound'] == '100% ?'
        assert row['bad'] is None and row['blank'] is None and row['days'] == 1
        conn.commit()
        assert conn.execute('SELECT name FROM customers WHERE id=?',(1,)).fetchone()[0]=='Postgres Test Customer'
        conn.rollback()
        assert conn.execute("SELECT COUNT(*) FROM customers WHERE name LIKE '%Postgres%'").fetchone()[0] == 1
