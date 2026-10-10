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


def test_actual_cost_requires_reconciliation_and_reverses(order):
    import workflow_adjustments as a
    assert a.add_cost(1,'GOODS','Mal bedeli',2000,'EUR',1,date.today(),'Fatura')[0]
    assert a.add_cost(1,'FREIGHT','Navlun',200,'USD',.9,date.today(),'Navlun faturası')[0]
    assert not a.add_cost(1,'FREIGHT','Navlun',200,'USD',.9,date.today(),'Tekrar')[0]
    assert not a.add_cost(1,'BADFX','Navlun',200,'EUR',2,date.today(),'Yanlış kur')[0]
    assert flow.deliver(1,1,400,'D1',date.today())[0]
    assert a.cost_report().iloc[0]['gerçekleşen_katkı'] is None
    assert a.reconcile(1,True,'Tüm masraflar tamam')[0]
    report=a.cost_report().iloc[0]
    assert report['gerçek_birim_maliyet'] == 2.18
    assert report['gerçekleşen_katkı'] == pytest.approx(328)
    assert not a.reverse_cost(2,'COST-REVERSE','Hatalı fatura')[0]
    assert a.reconcile(1,False,'Navlun düzeltilecek')[0]
    assert a.reverse_cost(2,'COST-REVERSE','Hatalı fatura')[0]
    assert not a.reverse_cost(2,'SECOND-REVERSE','Tekrar')[0]
    assert a.reconcile(1,True,'Düzeltildi')[0]
    assert a.cost_report().iloc[0]['gerçekleşen_katkı']==400
    assert scalar('SELECT balance FROM cash_accounts') == 10000


def test_unpaid_customer_return_creates_hold_and_reduces_receivable(order):
    import workflow_adjustments as a
    assert flow.deliver(1,1,400,'D1',date.today())[0]
    assert a.return_delivery(1,100,'R1',date.today(),'Ambalaj hasarı')[0]
    assert scalar('SELECT credit_amount FROM receivables')==300
    assert ct.outstanding_receivables().iloc[0]['outstanding']==900
    assert scalar("SELECT quality_hold_kg FROM inventory_lots WHERE lot_number='RETURN-R1'")==100
    assert scalar('SELECT COUNT(*) FROM payables')==1
    assert not flow.deliver(1,2,100,'BLOCKED-RETURN',date.today())[0]
    assert flow.overview().iloc[0]['sevk_kg']==300
    assert flow.overview().iloc[0]['net_satış']==900
    assert flow.overview().iloc[0]['tahmini_kâr']==150
    assert not a.return_delivery(1,100,'R1',date.today(),'Tekrar')[0]
    assert not a.return_delivery(1,301,'R2',date.today(),'Fazla')[0]
    assert not ct.record_receivable_payment(1,1000,date.today(),1,'OVER','')[0]
    assert ct.record_receivable_payment(1,900,date.today(),1,'COLLECT','')[0]
    assert ct.outstanding_receivables().empty


def test_paid_return_creates_refund_payable_and_preserves_bank_until_payment(order):
    import workflow_adjustments as a
    assert flow.deliver(1,1,400,'D1',date.today())[0]
    assert ct.record_receivable_payment(1,1200,date.today(),1,'REC','')[0]
    assert a.return_delivery(1,100,'R1',date.today(),'Müşteri iadesi')[0]
    assert scalar('SELECT amount FROM payables WHERE id=2')==300
    assert scalar('SELECT balance FROM cash_accounts')==11200
    assert ct.record_payable_payment(2,300,date.today(),1,'REFUND','')[0]
    assert scalar('SELECT balance FROM cash_accounts')==10900
    assert ct.outstanding_receivables().empty
    assert not a.reverse_payment(1,'INVALID-REVERSE','İade sonrası')[0]


def test_part_paid_return_splits_credit_and_refund(order):
    import workflow_adjustments as a
    assert flow.deliver(1,1,400,'D1',date.today())[0]
    assert ct.record_receivable_payment(1,1000,date.today(),1,'REC','')[0]
    assert a.return_delivery(1,100,'R1',date.today(),'İade')[0]
    assert scalar('SELECT amount FROM payables WHERE id=2')==100
    assert ct.outstanding_receivables().empty
    assert a.return_delivery(1,100,'R2',date.today(),'İkinci iade')[0]
    assert scalar('SELECT amount FROM payables WHERE id=3')==300


def test_finance_reversal_is_atomic_and_idempotent(order):
    import workflow_adjustments as a
    assert ct.record_payable_payment(1,400,date.today(),1,'PAY','')[0]
    assert a.reverse_payment(1,'UNDO-PAY','Yanlış tutar')[0]
    assert scalar('SELECT paid_amount FROM payables')==0
    assert scalar('SELECT balance FROM cash_accounts')==10000
    assert scalar('SELECT SUM(amount) FROM finance_transactions')==0
    assert not a.reverse_payment(1,'AGAIN','Tekrar')[0]
    assert not a.reverse_payment(2,'UNDO-UNDO','Ters kaydın tersi')[0]


def test_return_rolls_back_on_credit_failure(order):
    import workflow_adjustments as a
    assert flow.deliver(1,1,400,'D1',date.today())[0]
    with ct.get_conn() as c:
        c.execute("CREATE TRIGGER credit_failure BEFORE UPDATE ON receivables BEGIN SELECT RAISE(ABORT,'test'); END")
    with pytest.raises(sqlite3.IntegrityError):
        a.return_delivery(1,100,'FAIL',date.today(),'Test rollback')
    assert scalar('SELECT COUNT(*) FROM workflow_returns')==0
    assert scalar('SELECT COUNT(*) FROM inventory_lots')==1
    assert scalar('SELECT COUNT(*) FROM payables')==1


def test_parallel_returns_cannot_exceed_delivered_quantity(order):
    import workflow_adjustments as a
    assert flow.deliver(1,1,400,'D1',date.today())[0]
    with ThreadPoolExecutor(max_workers=2) as pool:
        results=list(pool.map(lambda ref:a.return_delivery(1,300,ref,date.today(),'İade'),['R1','R2']))
    assert sum(ok for ok,_ in results)==1
    assert scalar('SELECT SUM(quantity_kg) FROM workflow_returns')==300


def test_viewer_cannot_adjust_costs_or_returns(order,monkeypatch):
    import workflow_adjustments as a
    monkeypatch.setattr(ct,'current_role',lambda:'VIEWER')
    assert not a.add_cost(1,'X','Mal bedeli',10,'EUR',1,date.today(),'X')[0]
    assert not a.reconcile(1,True,'X')[0]
    assert not a.return_delivery(1,10,'X',date.today(),'X')[0]
    assert not a.reverse_payment(1,'X','X')[0]
