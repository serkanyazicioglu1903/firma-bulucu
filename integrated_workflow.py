"""Transactional quote-to-cash pilot using the existing Control Tower records.

No external services or live database configuration are used by this module.
The v1 flow handles one product per quote and partial deliveries from its PO.
"""
import math
from datetime import date, timedelta

import streamlit as st


def core():
    import control_tower
    return control_tower


def init_workflow():
    import database
    if database.is_postgres():
        return
    with core().get_conn() as conn:
        conn.executescript("""
        CREATE TABLE IF NOT EXISTS workflow_orders (
            id INTEGER PRIMARY KEY,
            quote_id INTEGER NOT NULL UNIQUE,
            product_id INTEGER NOT NULL,
            purchase_order_id INTEGER NOT NULL UNIQUE,
            payable_id INTEGER NOT NULL UNIQUE,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS workflow_deliveries (
            id INTEGER PRIMARY KEY,
            workflow_id INTEGER NOT NULL,
            lot_id INTEGER NOT NULL,
            receivable_id INTEGER NOT NULL UNIQUE,
            reference TEXT NOT NULL UNIQUE,
            quantity_kg REAL NOT NULL CHECK(quantity_kg > 0),
            revenue_base REAL NOT NULL,
            cost_base REAL NOT NULL,
            base_currency TEXT NOT NULL,
            delivery_date TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS workflow_order_groups (
            id INTEGER PRIMARY KEY,
            reference TEXT NOT NULL UNIQUE,
            customer_id INTEGER NOT NULL REFERENCES customers(id),
            supplier TEXT NOT NULL,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS workflow_group_lines (
            id INTEGER PRIMARY KEY,
            group_id INTEGER NOT NULL REFERENCES workflow_order_groups(id),
            workflow_id INTEGER NOT NULL UNIQUE REFERENCES workflow_orders(id)
        );
        CREATE TRIGGER IF NOT EXISTS workflow_quote_frozen BEFORE UPDATE ON quotes
        WHEN EXISTS (SELECT 1 FROM workflow_orders WHERE quote_id=OLD.id)
        BEGIN SELECT RAISE(ABORT,'Siparişe dönüşen teklif değiştirilemez; yeni revizyon oluşturun.'); END;
        CREATE TRIGGER IF NOT EXISTS workflow_quote_no_delete BEFORE DELETE ON quotes
        WHEN EXISTS (SELECT 1 FROM workflow_orders WHERE quote_id=OLD.id)
        BEGIN SELECT RAISE(ABORT,'Siparişe bağlı teklif silinemez.'); END;
        """)
    from workflow_adjustments import init_adjustments
    init_adjustments()


def positive(value):
    return math.isfinite(float(value)) and float(value) > 0


def _audit(conn, action):
    # Kept in the same transaction as business records.
    conn.execute('''INSERT INTO audit_log (username,role,action,table_name,sql_preview)
                    VALUES (?,?,?,?,?)''',
                 ((st.session_state.get('ct_user') or {}).get('username', 'SYSTEM'),
                  core().current_role() or 'SYSTEM', action, 'workflow_orders', action))


def create_order(quote_id, product_id, supplier, warehouse_id, po_number, due_date):
    with core().get_conn() as conn:
        conn.execute('BEGIN IMMEDIATE')
        return _create_order(conn,quote_id,product_id,supplier,warehouse_id,po_number,due_date)


def _create_order(conn, quote_id, product_id, supplier, warehouse_id, po_number, due_date):
    ct = core()
    if ct.current_role() not in ('', 'SYSTEM', 'ADMIN'):
        return False, 'Bütünleşik sipariş açmak için yönetici yetkisi gerekir.'
    if not supplier.strip() or not po_number.strip():
        return False, 'Tedarikçi ve sipariş numarası zorunlu.'
    try:
        date.fromisoformat(str(due_date))
    except ValueError:
        return False, 'Geçerli ödeme tarihi girin.'
    if conn.execute('SELECT 1 FROM workflow_orders WHERE quote_id=?', (quote_id,)).fetchone():
        return False, 'Bu teklif zaten siparişe dönüştürülmüş.'
    q = conn.execute('SELECT * FROM quotes WHERE id=?', (quote_id,)).fetchone()
    p = conn.execute('SELECT * FROM product_catalog WHERE id=? AND active=1', (product_id,)).fetchone()
    if not q or q['status'] != 'Kabul':
        return False, 'Önce teklif durumunu Kabul olarak kaydedin.'
    if not p or p['name'] != q['product_name']:
        return False, 'Teklif ürünü ile katalog ürünü eşleşmiyor.'
    if not conn.execute('SELECT 1 FROM customers WHERE id=?', (q['customer_id'],)).fetchone():
        return False, 'Teklife geçerli müşteri bağlanmalı.'
    if not conn.execute('SELECT 1 FROM warehouses WHERE id=? AND active=1', (warehouse_id,)).fetchone():
        return False, 'Aktif depo seçilmeli.'
    if not all(positive(q[k]) for k in ('quantity_kg', 'buy_price_per_kg', 'sell_price_per_kg', 'buy_fx_to_base', 'sell_fx_to_base', 'total_cost_per_kg')):
        return False, 'Miktar, fiyatlar ve kurlar sıfırdan büyük olmalı.'
    if not 0 <= q['sales_commission_pct'] < 100 or q['customer_credit_days'] < 0:
        return False, 'Komisyon ve vade değerlerini düzeltin.'
    if conn.execute('SELECT 1 FROM purchase_orders WHERE po_number=?', (po_number.strip(),)).fetchone():
        return False, 'Sipariş numarası zaten kullanılıyor.'
    po = conn.execute('''INSERT INTO purchase_orders
        (po_number,supplier,product_id,product_name,quantity_kg,unit_price,currency,
         incoterm,order_date,destination_warehouse_id,status)
        VALUES (?,?,?,?,?,?,?,?,?,?,'Sipariş Verildi')''',
        (po_number.strip(),supplier.strip(),product_id,p['name'],q['quantity_kg'],q['buy_price_per_kg'],
         q['buy_currency'],q['incoterm'],str(date.today()),warehouse_id)).lastrowid
    payable = conn.execute('''INSERT INTO payables
        (supplier,purchase_order_id,invoice_no,due_date,amount,currency,fx_to_base,base_currency,notes)
        VALUES (?,?,?,?,?,?,?,?,?)''',
        (supplier.strip(),po,'',str(due_date),q['quantity_kg']*q['buy_price_per_kg'],q['buy_currency'],
         q['buy_fx_to_base'],q['base_currency'],'Siparişten oluşan planlanan borç; tedarikçi faturası bekleniyor.')).lastrowid
    conn.execute('INSERT INTO workflow_orders (quote_id,product_id,purchase_order_id,payable_id) VALUES (?,?,?,?)',
                 (quote_id,product_id,po,payable))
    if q['opportunity_id']:
        conn.execute("UPDATE opportunities SET stage='Sipariş',probability=90 WHERE id=? AND stage NOT IN ('Kazanıldı','Kaybedildi')", (q['opportunity_id'],))
    _audit(conn, 'Tekliften satın alma ve planlanan borç oluşturuldu')
    return True, 'Sipariş ve planlanan borç oluştu. İthalat/sevkiyatı Satın Alma & Stok bölümünden takip edin.'


def deliver(workflow_id, lot_id, quantity, reference, delivery_date):
    ct = core()
    if ct.current_role() not in ('', 'SYSTEM', 'ADMIN'):
        return False, 'Sevk ve alacak oluşturmak için yönetici yetkisi gerekir.'
    if not positive(quantity) or not reference.strip():
        return False, 'Pozitif miktar ve benzersiz sevk/fatura referansı gerekli.'
    try:
        day = date.fromisoformat(str(delivery_date))
    except ValueError:
        return False, 'Geçerli sevk tarihi girin.'
    with ct.get_conn() as conn:
        conn.execute('BEGIN IMMEDIATE')
        q = conn.execute('''SELECT q.*,w.purchase_order_id,w.product_id FROM workflow_orders w
            JOIN quotes q ON q.id=w.quote_id WHERE w.id=?''', (workflow_id,)).fetchone()
        lot = conn.execute('SELECT * FROM inventory_lots WHERE id=?', (lot_id,)).fetchone()
        if not q or not lot or lot['purchase_order_id'] != q['purchase_order_id'] or lot['product_id'] != q['product_id']:
            return False, 'Bu siparişe bağlı stok lotunu seçin.'
        if conn.execute('SELECT 1 FROM workflow_deliveries WHERE reference=?', (reference.strip(),)).fetchone():
            return False, 'Bu sevk referansı zaten işlendi.'
        if q['status'] != 'Kabul':
            return False, 'Teklif kabul durumunda olmalı.'
        # A held/rejected lot requires an explicit quality release before shipping.
        if lot['quality_status'] != 'Released' or float(lot['quality_hold_kg'] or 0) > 0:
            return False, 'Kalite blokesi var. Önce Kalite bölümünden lotu serbest bırakın.'
        if lot['expiry_date'] and date.fromisoformat(lot['expiry_date']) < day:
            return False, 'Son kullanma tarihi geçmiş lot sevk edilemez.'
        if conn.execute("SELECT 1 FROM regulatory_items WHERE product_id=? AND status='Bloke'", (q['product_id'],)).fetchone():
            return False, 'Ürün için bloke regülasyon kaydı var.'
        sent = conn.execute('SELECT COALESCE(SUM(quantity_kg),0) FROM workflow_deliveries WHERE workflow_id=?', (workflow_id,)).fetchone()[0]
        returned = conn.execute('SELECT COALESCE(SUM(r.quantity_kg),0) FROM workflow_returns r JOIN workflow_deliveries d ON d.id=r.delivery_id WHERE d.workflow_id=?', (workflow_id,)).fetchone()[0]
        sent -= returned
        available = float(lot['quantity_available_kg'])-float(lot['quantity_reserved_kg'] or 0)
        if quantity > available + 0.000001 or sent + quantity > q['quantity_kg'] + 0.000001:
            return False, 'Miktar kullanılabilir stoğu veya kalan satış miktarını aşıyor.'
        amount = round(quantity*q['sell_price_per_kg'], 2)
        ar = conn.execute('''INSERT INTO receivables
            (customer_id,invoice_no,invoice_date,due_date,amount,currency,fx_to_base,base_currency,opportunity_id,notes)
            VALUES (?,?,?,?,?,?,?,?,?,?)''',
            (q['customer_id'],reference.strip(),str(day),str(day+timedelta(days=q['customer_credit_days'])),amount,
             q['sell_currency'],q['sell_fx_to_base'],q['base_currency'],q['opportunity_id'],
             'Sevkiyattan oluşan alacak takibi; resmî e-fatura değildir.')).lastrowid
        revenue = amount*q['sell_fx_to_base']*(1-q['sales_commission_pct']/100)
        cost = quantity*q['total_cost_per_kg']
        conn.execute('''INSERT INTO workflow_deliveries
            (workflow_id,lot_id,receivable_id,reference,quantity_kg,revenue_base,cost_base,base_currency,delivery_date)
            VALUES (?,?,?,?,?,?,?,?,?)''', (workflow_id,lot_id,ar,reference.strip(),quantity,revenue,cost,q['base_currency'],str(day)))
        conn.execute('UPDATE inventory_lots SET quantity_available_kg=quantity_available_kg-? WHERE id=?', (quantity,lot_id))
        if sent+quantity >= q['quantity_kg']-0.000001 and q['opportunity_id']:
            conn.execute("UPDATE opportunities SET stage='Kazanıldı',probability=100,next_action='',due_date='' WHERE id=?", (q['opportunity_id'],))
        _audit(conn, 'Müşteri sevki: stok düşüldü ve alacak oluşturuldu')
    return True, 'Sevk, stok düşümü ve alacak birlikte kaydedildi. Tahsilatı Finans bölümünden girin.'


def overview():
    return core().query_df('''SELECT w.id,g.reference AS sipariş_grubu,q.id AS teklif, c.name AS müşteri,q.product_name AS ürün,
        po.po_number AS satın_alma,po.status AS satın_alma_durumu,q.quantity_kg AS sipariş_kg,
        COALESCE(d.qty,0) AS sevk_kg,q.quantity_kg-COALESCE(d.qty,0) AS kalan_kg,
        COALESCE(d.revenue,0) AS net_satış,COALESCE(d.cost,0) AS teklif_maliyeti,
        COALESCE(d.revenue-d.cost,0) AS tahmini_kâr,q.base_currency AS baz_para,
        p.amount-p.paid_amount AS kalan_tedarikçi_borcu,p.currency AS borç_parası
        FROM workflow_orders w JOIN quotes q ON q.id=w.quote_id
        JOIN customers c ON c.id=q.customer_id JOIN purchase_orders po ON po.id=w.purchase_order_id
        JOIN payables p ON p.id=w.payable_id
        LEFT JOIN workflow_group_lines gl ON gl.workflow_id=w.id
        LEFT JOIN workflow_order_groups g ON g.id=gl.group_id
        LEFT JOIN (SELECT d.workflow_id,SUM(d.quantity_kg-COALESCE(r.qty,0)) qty,
                   SUM(d.revenue_base-COALESCE(r.revenue,0)) revenue,
                   SUM(d.cost_base*(1-COALESCE(r.qty,0)/d.quantity_kg)) cost
                   FROM workflow_deliveries d LEFT JOIN
                   (SELECT delivery_id,SUM(quantity_kg) qty,SUM(revenue_base) revenue FROM workflow_returns GROUP BY delivery_id) r ON r.delivery_id=d.id
                   GROUP BY d.workflow_id) d ON d.workflow_id=w.id
        ORDER BY w.id DESC''')


def render_workflow():
    init_workflow()
    with st.expander('🔗 Tekliften tahsilata • Bütünleşik işlem merkezi', expanded=True):
        st.caption('Kabul edilen teklif → satın alma ve borç → ithalat/stok → kalite serbest bırakma → müşteri sevki ve alacak → tahsilat.')
        summary = overview()
        if not summary.empty:
            st.dataframe(summary, hide_index=True, width='stretch')
            st.caption('Kâr, sevk edilen miktar ve kayıtlı teklif maliyetiyle hesaplanan tahmindir; gerçekleşen masraf mutabakatı değildir. Para birimleri ayrı gösterilir.')
        else:
            st.info('İlk işlem için müşteri, katalog ürünü ve depo ekleyin; Teklif & Kârlılık bölümünde teklifi Kabul durumuna getirin.')
        quotes = core().query_df("SELECT id,product_name FROM quotes WHERE status='Kabul' AND id NOT IN (SELECT quote_id FROM workflow_orders)")
        products = core().query_df('SELECT id,name,supplier FROM product_catalog WHERE active=1')
        warehouses = core().query_df('SELECT id,name FROM warehouses WHERE active=1')
        if not quotes.empty and not products.empty and not warehouses.empty:
            with st.form('workflow_order'):
                qid = st.selectbox('Kabul edilen teklif', quotes.id.tolist(), format_func=lambda x: f'#{x} · {quotes.set_index("id").loc[x,"product_name"]}')
                pid = st.selectbox('Katalog ürünü', products.id.tolist(), format_func=lambda x: products.set_index('id').loc[x,'name'])
                supplier_names = sorted(set(products.supplier.dropna().tolist() + core().query_df(
                    "SELECT name FROM customers WHERE sector='Tedarikçi / Üretici'").name.tolist()) - {''})
                supplier = st.selectbox('Tedarikçi / üretici', supplier_names, accept_new_options=True) or ''
                wid = st.selectbox('Varış deposu', warehouses.id.tolist(), format_func=lambda x: warehouses.set_index('id').loc[x,'name'])
                number = st.text_input('Satın alma sipariş no')
                due = st.date_input('Planlanan ödeme tarihi')
                if st.form_submit_button('Sipariş ve borç oluştur'):
                    ok, msg = create_order(qid,pid,supplier,wid,number,due)
                    (st.success if ok else st.error)(msg)
                    if ok:
                        st.rerun()
        if len(quotes)>=2 and not warehouses.empty:
            with st.form('workflow_batch'):
                selected=st.multiselect('Çok kalemli sipariş teklifleri',quotes.id.tolist(),format_func=lambda x:f'#{x} · {quotes.set_index("id").loc[x,"product_name"]}')
                batch_ref=st.text_input('Ortak sipariş referansı')
                batch_supplier=st.text_input('Çok kalemli sipariş tedarikçisi')
                batch_warehouse=st.selectbox('Ortak varış deposu',warehouses.id.tolist(),format_func=lambda x:warehouses.set_index('id').loc[x,'name'])
                batch_due=st.date_input('Ortak planlanan ödeme tarihi')
                st.caption('Aynı müşterinin kabul edilmiş tekliflerini seçin. Her kalem ayrı stok ve maliyetle izlenir; bir kalem hatalıysa hiçbir kalem kaydedilmez.')
                if st.form_submit_button('Tüm kalemleri birlikte siparişe dönüştür'):
                    ok,msg=create_order_batch(selected,batch_supplier,batch_warehouse,batch_ref,batch_due)
                    (st.success if ok else st.error)(msg)
                    if ok:
                        st.rerun()
        lots = core().query_df('''SELECT l.id,l.lot_number,l.quantity_available_kg,w.id AS workflow_id
             FROM inventory_lots l JOIN workflow_orders w ON w.purchase_order_id=l.purchase_order_id
             WHERE l.quantity_available_kg>0''')
        if not lots.empty:
            with st.form('workflow_delivery'):
                lid = st.selectbox('Sevk edilecek lot',lots.id.tolist(),format_func=lambda x:f'#{x} · {lots.set_index("id").loc[x,"lot_number"]}')
                qty = st.number_input('Müşteriye sevk (kg)',min_value=0.0,step=25.0)
                ref = st.text_input('Benzersiz sevk / fatura referansı')
                day = st.date_input('Müşteri sevk tarihi')
                if st.form_submit_button('Stoktan düş ve alacak oluştur'):
                    ok,msg=deliver(int(lots.set_index('id').loc[lid,'workflow_id']),lid,qty,ref,day)
                    (st.success if ok else st.error)(msg)
                    if ok:
                        st.rerun()

        from workflow_adjustments_ui import render_adjustments
        render_adjustments(summary)


class BatchOrderError(ValueError):
    pass


def create_order_batch(quote_ids, supplier, warehouse_id, reference, due_date):
    """One multi-line header, child POs per product; all rows commit or none do."""
    if core().current_role() not in ('','SYSTEM','ADMIN'):
        return False, 'Çok kalemli sipariş için yönetici yetkisi gerekli.'
    if len(quote_ids)<2 or len(set(quote_ids))!=len(quote_ids) or not reference.strip():
        return False, 'En az iki farklı kabul edilmiş teklif ve sipariş referansı seçin.'
    try:
        with core().get_conn() as conn:
            conn.execute('BEGIN IMMEDIATE')
            if conn.execute('SELECT 1 FROM workflow_order_groups WHERE reference=?',(reference.strip(),)).fetchone():
                return False, 'Sipariş grup referansı zaten kullanılmış.'
            first=conn.execute('SELECT customer_id FROM quotes WHERE id=?',(quote_ids[0],)).fetchone()
            if not first or not first["customer_id"]:
                return False, 'İlk teklifte geçerli müşteri bulunamadı.'
            group_id=conn.execute('INSERT INTO workflow_order_groups (reference,customer_id,supplier) VALUES (?,?,?)',
                                  (reference.strip(),first['customer_id'],supplier.strip())).lastrowid
            for line,quote_id in enumerate(quote_ids,1):
                q=conn.execute('SELECT * FROM quotes WHERE id=?',(quote_id,)).fetchone()
                if not q or q['customer_id']!=first['customer_id']:
                    raise BatchOrderError('Tüm kalemler aynı müşteriye ait olmalı; hiçbir sipariş oluşturulmadı.')
                products=conn.execute('SELECT id FROM product_catalog WHERE name=? AND active=1',(q['product_name'],)).fetchall()
                if len(products)!=1:
                    raise BatchOrderError('Her teklif ürünü katalogda tek bir aktif ürünle eşleşmeli.')
                ok,message=_create_order(conn,quote_id,products[0]['id'],supplier,warehouse_id,
                                         reference.strip()+'-'+str(line),due_date)
                if not ok:
                    raise BatchOrderError('Kalem '+str(line)+': '+message+' Hiçbir kalem kaydedilmedi.')
                wid=conn.execute('SELECT id FROM workflow_orders WHERE quote_id=?',(quote_id,)).fetchone()['id']
                conn.execute('INSERT INTO workflow_group_lines (group_id,workflow_id) VALUES (?,?)',(group_id,wid))
            _audit(conn,'Çok kalemli sipariş grubu oluşturuldu: '+reference.strip())
        return True, 'Tüm kalemler tek sipariş grubuna bağlandı; ürün bazında stok, borç ve maliyet izlenebilir.'
    except BatchOrderError as exc:
        return False,str(exc)
