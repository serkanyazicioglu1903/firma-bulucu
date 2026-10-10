"""Audited actual costs, customer returns and financial reversals.

All amounts are captured with their explicit document FX, never a live FX lookup.
No destructive deletion or external financial action occurs here.
"""
from datetime import date
from decimal import Decimal, ROUND_HALF_UP
import math


def core():
    import control_tower
    return control_tower


def init_adjustments():
    import database
    if database.is_postgres():
        return
    with core().get_conn() as conn:
        conn.executescript("""
        CREATE TABLE IF NOT EXISTS workflow_costs (
            id INTEGER PRIMARY KEY,
            workflow_id INTEGER NOT NULL REFERENCES workflow_orders(id),
            reference TEXT NOT NULL UNIQUE,
            category TEXT NOT NULL,
            amount REAL NOT NULL,
            currency TEXT NOT NULL,
            fx_to_base REAL NOT NULL,
            amount_base REAL NOT NULL,
            document_date TEXT NOT NULL,
            reason TEXT NOT NULL,
            reverses_id INTEGER UNIQUE REFERENCES workflow_costs(id)
        );
        CREATE TABLE IF NOT EXISTS workflow_reconciliations (
            workflow_id INTEGER PRIMARY KEY REFERENCES workflow_orders(id),
            closed INTEGER NOT NULL DEFAULT 0,
            note TEXT NOT NULL DEFAULT ''
        );
        CREATE TABLE IF NOT EXISTS workflow_returns (
            id INTEGER PRIMARY KEY,
            delivery_id INTEGER NOT NULL REFERENCES workflow_deliveries(id),
            reference TEXT NOT NULL UNIQUE,
            quantity_kg REAL NOT NULL,
            credit_amount REAL NOT NULL,
            revenue_base REAL NOT NULL,
            return_lot_id INTEGER NOT NULL UNIQUE REFERENCES inventory_lots(id),
            refund_payable_id INTEGER REFERENCES payables(id),
            return_date TEXT NOT NULL,
            reason TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS finance_reversals (
            id INTEGER PRIMARY KEY,
            transaction_id INTEGER NOT NULL UNIQUE REFERENCES finance_transactions(id),
            reversal_transaction_id INTEGER NOT NULL UNIQUE REFERENCES finance_transactions(id),
            reference TEXT NOT NULL UNIQUE,
            reason TEXT NOT NULL
        );
        """)


def _allowed():
    return core().current_role() in ('', 'SYSTEM', 'ADMIN')


def _audit(conn, message):
    from integrated_workflow import _audit as audit
    audit(conn, message)


def _money(value):
    return float(Decimal(str(value)).quantize(Decimal('.01'), rounding=ROUND_HALF_UP))


def _positive(value):
    try:
        return math.isfinite(float(value)) and float(value) > 0
    except (TypeError, ValueError):
        return False


CATEGORIES = ('Mal bedeli', 'Navlun', 'Gümrük', 'Depo / elleçleme', 'Finansman', 'Kur farkı', 'Diğer')


def add_cost(workflow_id, reference, category, amount, currency, fx_to_base, document_date, reason):
    if not _allowed():
        return False, 'Bu işlem için yönetici yetkisi gerekir.'
    if not reference.strip() or not reason.strip() or category not in CATEGORIES:
        return False, 'Belge referansı, kategori ve açıklama zorunlu.'
    if not _positive(amount) or not _positive(fx_to_base) or currency not in ('EUR', 'USD', 'GBP', 'TRY'):
        return False, 'Pozitif tutar, kur ve desteklenen para birimi girin.'
    day=date.fromisoformat(str(document_date))
    with core().get_conn() as conn:
        conn.execute('BEGIN IMMEDIATE')
        q=conn.execute('SELECT q.base_currency FROM workflow_orders w JOIN quotes q ON q.id=w.quote_id WHERE w.id=?',(workflow_id,)).fetchone()
        if not q:
            return False, 'Sipariş bulunamadı.'
        if currency==q['base_currency'] and float(fx_to_base)!=1:
            return False, 'Baz para birimi için kur 1 olmalı.'
        if conn.execute('SELECT 1 FROM workflow_reconciliations WHERE workflow_id=? AND closed=1',(workflow_id,)).fetchone():
            return False, 'Mutabakat kapalı; önce açıklamayla yeniden açın.'
        if conn.execute('SELECT 1 FROM workflow_costs WHERE reference=?',(reference.strip(),)).fetchone():
            return False, 'Bu masraf referansı zaten kaydedilmiş.'
        conn.execute('''INSERT INTO workflow_costs
            (workflow_id,reference,category,amount,currency,fx_to_base,amount_base,document_date,reason)
            VALUES (?,?,?,?,?,?,?,?,?)''',(workflow_id,reference.strip(),category,float(amount),currency,float(fx_to_base),_money(float(amount)*float(fx_to_base)),str(day),reason.strip()))
        _audit(conn,'Gerçekleşen maliyet kaydedildi: '+reference.strip())
    return True, 'Gerçekleşen maliyet kaydedildi. Bu kayıt ayrıca banka hareketi oluşturmaz.'


def reverse_cost(cost_id, reference, reason):
    if not _allowed() or not reference.strip() or not reason.strip():
        return False, 'Yönetici yetkisi, benzersiz referans ve gerekçe gerekli.'
    with core().get_conn() as conn:
        conn.execute('BEGIN IMMEDIATE')
        c=conn.execute('SELECT * FROM workflow_costs WHERE id=?',(cost_id,)).fetchone()
        if not c or c['reverses_id'] is not None:
            return False, 'Asıl maliyet kaydını seçin.'
        if conn.execute('SELECT 1 FROM workflow_costs WHERE reverses_id=? OR reference=?',(cost_id,reference.strip())).fetchone():
            return False, 'Bu masraf zaten ters kaydedildi veya referans kullanılıyor.'
        if conn.execute('SELECT 1 FROM workflow_reconciliations WHERE workflow_id=? AND closed=1',(c['workflow_id'],)).fetchone():
            return False, 'Önce mutabakatı yeniden açın.'
        conn.execute('''INSERT INTO workflow_costs (workflow_id,reference,category,amount,currency,fx_to_base,amount_base,document_date,reason,reverses_id)
            VALUES (?,?,?,?,?,?,?,?,?,?)''',(c['workflow_id'],reference.strip(),c['category'],-c['amount'],c['currency'],c['fx_to_base'],-c['amount_base'],str(date.today()),reason.strip(),cost_id))
        _audit(conn,'Maliyet ters kaydı: '+reference.strip())
    return True, 'Masraf silinmeden ters kayıt oluşturuldu.'


def reconcile(workflow_id, closed, note):
    if not _allowed() or not note.strip():
        return False, 'Yönetici yetkisi ve mutabakat açıklaması gerekli.'
    with core().get_conn() as conn:
        conn.execute('BEGIN IMMEDIATE')
        w=conn.execute('SELECT * FROM workflow_orders WHERE id=?',(workflow_id,)).fetchone()
        if not w:
            return False, 'Sipariş bulunamadı.'
        goods=conn.execute("SELECT COALESCE(SUM(amount_base),0) AS amount FROM workflow_costs WHERE workflow_id=? AND category='Mal bedeli'",(workflow_id,)).fetchone()['amount']
        if closed and goods <= 0:
            return False, 'Gerçekleşen mal bedelini girin; ardından tüm masrafların tamamlandığını doğrulayın.'
        conn.execute('''INSERT INTO workflow_reconciliations (workflow_id,closed,note) VALUES (?,?,?)
            ON CONFLICT(workflow_id) DO UPDATE SET closed=excluded.closed,note=excluded.note''',(workflow_id,int(closed),note.strip()))
        _audit(conn,('Maliyet mutabakatı kapatıldı: ' if closed else 'Maliyet mutabakatı yeniden açıldı: ')+note.strip())
    return True, 'Mutabakat durumu kaydedildi.'


def return_delivery(delivery_id, quantity, reference, return_date, reason):
    if not _allowed() or not reference.strip() or not reason.strip() or not _positive(quantity):
        return False, 'Yönetici yetkisi, pozitif miktar, referans ve iade nedeni gerekli.'
    day=date.fromisoformat(str(return_date))
    with core().get_conn() as conn:
        conn.execute('BEGIN IMMEDIATE')
        d=conn.execute('''SELECT d.*,r.amount,r.paid_amount,r.credit_amount,r.customer_id,r.currency,r.fx_to_base,
            r.status AS ar_status,q.opportunity_id,w.purchase_order_id,w.product_id
            FROM workflow_deliveries d JOIN receivables r ON r.id=d.receivable_id
            JOIN workflow_orders w ON w.id=d.workflow_id JOIN quotes q ON q.id=w.quote_id WHERE d.id=?''',(delivery_id,)).fetchone()
        if not d or d['ar_status']=='İptal':
            return False, 'Geçerli teslimat bulunamadı.'
        if day < date.fromisoformat(d['delivery_date']):
            return False, 'İade tarihi teslimattan önce olamaz.'
        if conn.execute('SELECT 1 FROM workflow_returns WHERE reference=?',(reference.strip(),)).fetchone():
            return False, 'Bu iade referansı zaten işlendi.'
        returned=conn.execute('SELECT COALESCE(SUM(quantity_kg),0) AS qty,COALESCE(SUM(credit_amount),0) AS credit,COALESCE(SUM(revenue_base),0) AS revenue FROM workflow_returns WHERE delivery_id=?',(delivery_id,)).fetchone()
        if quantity+returned['qty']>d['quantity_kg']+1e-6:
            return False, 'İade miktarı teslim edilen kalan miktarı aşamaz.'
        final=abs(quantity+returned['qty']-d['quantity_kg'])<1e-6
        credit=_money(d['amount']-returned['credit'] if final else min(d['amount']-returned['credit'],d['amount']*quantity/d['quantity_kg']))
        credit=min(_money(d['amount']-returned['credit']),credit)
        revenue=d['revenue_base']-returned['revenue'] if final else d['revenue_base']*quantity/d['quantity_kg']
        open_amount=max(d['amount']-d['paid_amount']-d['credit_amount'],0)
        refund=_money(max(credit-open_amount,0))
        lot=conn.execute('SELECT * FROM inventory_lots WHERE id=?',(d['lot_id'],)).fetchone()
        new_lot=conn.execute('''INSERT INTO inventory_lots
            (product_id,product_name,warehouse_id,lot_number,expiry_date,quantity_received_kg,quantity_available_kg,
             quantity_reserved_kg,unit_cost,currency,purchase_order_id,received_date,quality_status,quality_hold_kg,notes)
             VALUES (?,?,?,?,?,?,?,0,?,?,?,?,'HOLD',?,?)''',
            (lot['product_id'],lot['product_name'],lot['warehouse_id'],'RETURN-'+reference.strip(),lot['expiry_date'],quantity,quantity,lot['unit_cost'],lot['currency'],d['purchase_order_id'],str(day),quantity,reason.strip())).lastrowid
        quality_id=conn.execute("""INSERT INTO quality_cases
            (case_no,opened_date,customer_id,product_id,product_name,inventory_lot_id,purchase_order_id,
             complaint_type,affected_quantity_kg,currency,description,immediate_action)
            VALUES (?,?,?,?,?,?,?,'Müşteri iadesi',?,?,?,?)""",
            ('RET-'+str(new_lot)+'-'+reference.strip(),str(day),d['customer_id'],lot['product_id'],
             lot['product_name'],new_lot,d['purchase_order_id'],quantity,d['currency'],reason.strip(),
             'İade stoğu ayrı lotta HOLD. İnceleme sonrası serbest bırakma veya imha kararı gerekli.')).lastrowid
        conn.execute('UPDATE inventory_lots SET quality_case_id=? WHERE id=?',(quality_id,new_lot))
        refund_id=None
        if refund>0:
            name=conn.execute('SELECT name FROM customers WHERE id=?',(d['customer_id'],)).fetchone()['name']
            refund_id=conn.execute('''INSERT INTO payables
                (supplier,invoice_no,invoice_date,due_date,amount,currency,fx_to_base,base_currency,notes)
                VALUES (?,?,?,?,?,?,?,?,?)''',('Müşteri iadesi: '+name,reference.strip(),str(day),str(day),refund,d['currency'],d['fx_to_base'],d['base_currency'],'Müşteri iade geri ödemesi; teslimat #'+str(delivery_id))).lastrowid
        conn.execute('''INSERT INTO workflow_returns
            (delivery_id,reference,quantity_kg,credit_amount,revenue_base,return_lot_id,refund_payable_id,return_date,reason)
            VALUES (?,?,?,?,?,?,?,?,?)''',(delivery_id,reference.strip(),quantity,credit,revenue,new_lot,refund_id,str(day),reason.strip()))
        total_credit=d['credit_amount']+credit
        status='Kapandı' if d['paid_amount']+total_credit>=d['amount']-.0001 else 'Kısmi'
        conn.execute('UPDATE receivables SET credit_amount=?,status=? WHERE id=?',(total_credit,status,d['receivable_id']))
        if d['opportunity_id']:
            conn.execute("UPDATE opportunities SET stage='Problem / Koruma',next_action='Müşteri iadesi / çözüm takibi' WHERE id=?",(d['opportunity_id'],))
        _audit(conn,'Müşteri iadesi, HOLD lot ve alacak mahsubu: '+reference.strip())
    return True, 'İade ayrı HOLD lotuna alındı; alacak mahsup edildi. Varsa geri ödeme borcu Finans bölümünde.'


def reverse_payment(transaction_id, reference, reason):
    if not _allowed() or not reference.strip() or not reason.strip():
        return False, 'Yönetici yetkisi, referans ve gerekçe gerekli.'
    with core().get_conn() as conn:
        conn.execute('BEGIN IMMEDIATE')
        t=conn.execute('SELECT * FROM finance_transactions WHERE id=?',(transaction_id,)).fetchone()
        if not t or t['transaction_type'] not in ('Tahsilat','Ödeme') or not _positive(t['amount']):
            return False, 'Asıl tahsilat/ödeme işlemini seçin.'
        if conn.execute('SELECT 1 FROM finance_reversals WHERE transaction_id=? OR reference=?',(transaction_id,reference.strip())).fetchone():
            return False, 'İşlem zaten ters kaydedildi veya referans kullanılıyor.'
        if conn.execute('SELECT 1 FROM finance_transactions WHERE reference=?',(reference.strip(),)).fetchone():
            return False, 'Bu finans hareketi referansı zaten kullanılıyor.'
        table,key=('receivables','receivable_id') if t['transaction_type']=='Tahsilat' else ('payables','payable_id')
        target=conn.execute('SELECT * FROM '+table+' WHERE id=?',(t[key],)).fetchone()
        if not target or target['paid_amount']+1e-6<t['amount']:
            return False, 'Finans kaydı tutarsız; işlem durduruldu.'
        if table=='receivables' and target['credit_amount']>0:
            return False, 'İade mahsubu olan tahsilatı ters çevirmeyin; müşteri geri ödeme borcunu kullanın.'
        if t['account_id'] and not conn.execute('SELECT 1 FROM cash_accounts WHERE id=?',(t['account_id'],)).fetchone():
            return False, 'Asıl banka/kasa hesabı bulunamadı.'
        new_paid=_money(target['paid_amount']-t['amount'])
        conn.execute('UPDATE '+table+' SET paid_amount=?,status=? WHERE id=?',(new_paid,'Açık' if new_paid==0 else 'Kısmi',t[key]))
        reversal=conn.execute('''INSERT INTO finance_transactions
            (transaction_type,receivable_id,payable_id,transaction_date,amount,currency,fx_to_base,base_currency,account_id,reference,notes)
            VALUES (?,?,?,?,?,?,?,?,?,?,?)''',(t['transaction_type']+' Ters Kayıt',t['receivable_id'],t['payable_id'],str(date.today()),-t['amount'],t['currency'],t['fx_to_base'],t['base_currency'],t['account_id'],reference.strip(),reason.strip())).lastrowid
        if t['account_id']:
            delta=-t['amount'] if table=='receivables' else t['amount']
            conn.execute('UPDATE cash_accounts SET balance=balance+? WHERE id=?',(delta,t['account_id']))
        conn.execute('INSERT INTO finance_reversals (transaction_id,reversal_transaction_id,reference,reason) VALUES (?,?,?,?)',(transaction_id,reversal,reference.strip(),reason.strip()))
        _audit(conn,'Finans ters kaydı: '+reference.strip())
    return True, 'Asıl hareket korunarak ters kayıt oluşturuldu; banka ve bakiye birlikte güncellendi.'


def cost_report():
    return core().query_df('''SELECT w.id,q.product_name AS ürün,q.base_currency AS baz_para,
        q.quantity_kg AS sipariş_kg,COALESCE(d.qty,0)-COALESCE(r.qty,0) AS net_sevk_kg,
        COALESCE(d.revenue,0)-COALESCE(r.revenue,0) AS net_satış,
        COALESCE(c.cost,0) AS kaydedilen_gerçek_maliyet,
        CASE WHEN m.closed=1 THEN 'Mutabık' ELSE 'Eksik / açık' END AS maliyet_durumu,
        CASE WHEN m.closed=1 THEN COALESCE(c.cost,0)/q.quantity_kg END AS gerçek_birim_maliyet,
        CASE WHEN m.closed=1 THEN (COALESCE(d.revenue,0)-COALESCE(r.revenue,0))-
            (COALESCE(d.qty,0)-COALESCE(r.qty,0))*COALESCE(c.cost,0)/q.quantity_kg END AS gerçekleşen_katkı
        FROM workflow_orders w JOIN quotes q ON q.id=w.quote_id
        LEFT JOIN (SELECT workflow_id,SUM(amount_base) cost FROM workflow_costs GROUP BY workflow_id) c ON c.workflow_id=w.id
        LEFT JOIN (SELECT workflow_id,SUM(quantity_kg) qty,SUM(revenue_base) revenue FROM workflow_deliveries GROUP BY workflow_id) d ON d.workflow_id=w.id
        LEFT JOIN (SELECT d.workflow_id,SUM(r.quantity_kg) qty,SUM(r.revenue_base) revenue FROM workflow_returns r JOIN workflow_deliveries d ON d.id=r.delivery_id GROUP BY d.workflow_id) r ON r.workflow_id=w.id
        LEFT JOIN workflow_reconciliations m ON m.workflow_id=w.id ORDER BY w.id DESC''')
