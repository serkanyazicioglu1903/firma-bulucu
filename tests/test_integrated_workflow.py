from datetime import date, timedelta
import sqlite3
from concurrent.futures import ThreadPoolExecutor

import pytest
import control_tower as ct
import integrated_workflow as flow
from security_admin import init_security_tables


@pytest.fixture
def order():
    ct.init_db()
    init_security_tables(ct.DB_PATH)
    flow.init_workflow()
    with ct.get_conn() as c:
        c.execute("INSERT INTO customers (name) VALUES ('Synthetic Customer')")
        c.execute("INSERT INTO product_catalog (name,supplier,active) VALUES ('Test Ingredient','Synthetic Factory',1)")
        c.execute("INSERT INTO warehouses (name) VALUES ('Test Warehouse')")
        c.execute("INSERT INTO opportunities (customer_id,product,stage) VALUES (1,'Test Ingredient','Teklif')")
        c.execute('''INSERT INTO quotes (customer_id,opportunity_id,product_name,quantity_kg,
            buy_price_per_kg,sell_price_per_kg,total_cost_per_kg,customer_credit_days,status)
            VALUES (1,1,'Test Ingredient',1000,2,3,2.5,90,'Kabul')''')
        c.execute("INSERT INTO cash_accounts (name,balance) VALUES ('Test EUR',10000)")
    assert flow.create_order(1,1,'Synthetic Factory',1,'PO-TEST',date.today())[0]
    with ct.get_conn() as c:
        c.execute("INSERT INTO shipments (purchase_order_id,shipment_ref,quantity_kg,destination_warehouse_id,lot_number) VALUES (1,'TEST',1000,1,'LOT-TEST')")
    assert ct.receive_shipment_to_stock(1)[0]
    return 1


def scalar(sql):
    with ct.get_conn() as c:
        return c.execute(sql).fetchone()[0]


def test_quote_to_cash_and_management_profit(order):
    assert not flow.create_order(1,1,'Synthetic Factory',1,'PO-AGAIN',date.today())[0]
    assert scalar('SELECT COUNT(*) FROM payables') == 1
    assert not ct.receive_shipment_to_stock(1)[0]
    assert ct.set_lot_quality_status(1,'HOLD',hold_kg=100)[0]
    assert not flow.deliver(1,1,400,'INV-1',date.today())[0]
    assert scalar('SELECT COUNT(*) FROM receivables') == 0
    assert ct.set_lot_quality_status(1,'Released')[0]
    assert flow.deliver(1,1,400,'INV-1',date.today())[0]
    assert not flow.deliver(1,1,400,'INV-1',date.today())[0]
    assert not flow.deliver(1,1,700,'INV-OVER',date.today())[0]
    assert flow.deliver(1,1,600,'INV-2',date.today())[0]
    assert scalar('SELECT quantity_available_kg FROM inventory_lots') == 0
    assert scalar('SELECT stage FROM opportunities') == 'Kazanıldı'
    assert scalar('SELECT SUM(amount) FROM receivables') == 3000
    assert ct.record_payable_payment(1,2000,date.today(),1,'PAY-1','')[0]
    assert ct.record_receivable_payment(1,1200,date.today(),1,'REC-1','')[0]
    assert ct.record_receivable_payment(2,1800,date.today(),1,'REC-2','')[0]
    assert scalar('SELECT balance FROM cash_accounts') == 11000
    assert flow.overview().iloc[0]['tahmini_kâr'] == 500
    assert scalar('SELECT COUNT(*) FROM audit_log') >= 3


def test_failed_delivery_rolls_back_all_records(order):
    with ct.get_conn() as c:
        c.execute("CREATE TRIGGER stop_delivery BEFORE UPDATE ON inventory_lots BEGIN SELECT RAISE(ABORT,'forced failure'); END")
    with pytest.raises(sqlite3.IntegrityError):
        flow.deliver(1,1,200,'ROLLBACK',date.today())
    assert scalar('SELECT COUNT(*) FROM receivables') == 0
    assert scalar('SELECT COUNT(*) FROM workflow_deliveries') == 0
    assert scalar('SELECT quantity_available_kg FROM inventory_lots') == 1000


def test_expiry_and_regulatory_block(order):
    with ct.get_conn() as c:
        c.execute('UPDATE inventory_lots SET expiry_date=?', (str(date.today()-timedelta(days=1)),))
    assert not flow.deliver(1,1,10,'EXPIRED',date.today())[0]
    with ct.get_conn() as c:
        c.execute("UPDATE inventory_lots SET expiry_date='' ")
        c.execute("INSERT INTO regulatory_items (product_id,product_name,market_country,requirement_type,requirement,status) VALUES (1,'Test Ingredient','TR','Import','Synthetic requirement','Bloke')")
    assert not flow.deliver(1,1,10,'BLOCKED',date.today())[0]


def test_duplicate_payment_and_invalid_numbers(order):
    for amount in (float('nan'),float('inf'),-1,0):
        assert not ct.record_payable_payment(1,amount,date.today(),1,'BAD','')[0]
    assert ct.record_payable_payment(1,300,date.today(),1,'RETRY','')[0]
    assert not ct.record_payable_payment(1,300,date.today(),1,'RETRY','')[0]
    assert scalar('SELECT balance FROM cash_accounts') == 9700
    with ct.get_conn() as c:
        c.execute("UPDATE payables SET status='İptal'")
    assert not ct.record_payable_payment(1,100,date.today(),1,'CANCELLED','')[0]


def test_parallel_stock_receive_posts_once():
    ct.init_db()
    with ct.get_conn() as c:
        c.execute("INSERT INTO purchase_orders (po_number,supplier,product_name,quantity_kg,destination_warehouse_id) VALUES ('P','Test','Test',100,1)")
        c.execute("INSERT INTO shipments (purchase_order_id,quantity_kg,destination_warehouse_id) VALUES (1,100,1)")
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(ct.receive_shipment_to_stock,[1,1]))
    assert sum(ok for ok,_ in results) == 1
    assert scalar('SELECT COUNT(*) FROM inventory_lots') == 1


def test_parallel_payment_does_not_oversettle(order):
    with ThreadPoolExecutor(max_workers=2) as pool:
        results=list(pool.map(lambda x:ct.record_payable_payment(1,1500,date.today(),1,str(x),''),[1,2]))
    assert sum(ok for ok,_ in results) == 1
    assert scalar('SELECT paid_amount FROM payables') == 1500


def test_viewer_cannot_mutate_workflow(order,monkeypatch):
    monkeypatch.setattr(ct,'current_role',lambda:'VIEWER')
    assert not flow.deliver(1,1,10,'DENIED',date.today())[0]
    assert not flow.create_order(1,1,'Test',1,'DENIED',date.today())[0]


def test_partial_deliveries_cannot_exceed_reserved_stock(order):
    with ct.get_conn() as c:
        c.execute('UPDATE inventory_lots SET quantity_reserved_kg=800')
    assert not flow.deliver(1,1,201,'RESERVED',date.today())[0]
    assert flow.deliver(1,1,200,'AVAILABLE',date.today())[0]


def test_order_quote_is_immutable(order):
    with pytest.raises(sqlite3.IntegrityError):
        with ct.get_conn() as c:
            c.execute('UPDATE quotes SET sell_price_per_kg=99 WHERE id=1')
    assert scalar('SELECT sell_price_per_kg FROM quotes') == 3


def test_integrated_ui_can_deliver_order(order):
    from pathlib import Path
    from streamlit.testing.v1 import AppTest
    app=AppTest.from_file(str(Path(__file__).resolve().parents[1]/'app.py'),default_timeout=60)
    app.session_state['ct_user']={'username':'test','display_name':'Test','role':'ADMIN'}
    app.session_state['ct_session_id']='isolated-test'
    app.run()
    assert not app.exception
    next(x for x in app.number_input if x.label=='Müşteriye sevk (kg)').set_value(100)
    next(x for x in app.text_input if x.label=='Benzersiz sevk / fatura referansı').set_value('UI-DELIVERY')
    next(x for x in app.button if x.label=='Stoktan düş ve alacak oluştur').click()
    app.run()
    assert not app.exception
    assert scalar('SELECT quantity_available_kg FROM inventory_lots') == 900
    assert scalar('SELECT amount FROM receivables') == 300
