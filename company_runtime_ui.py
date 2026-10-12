"""Exclusive company workspace using the signed, dedicated-role runtime."""
from uuid import uuid4
import streamlit as st
from scripts.company_runtime import (runtime_mode, execute_request, WRITE_MODE,
                                    OWNED_READ_SECTIONS, CRM_READ_SECTIONS, EXTRA_READS)
from scripts.group_company_catalog import COMPANY_LABELS
from scripts.company_session_principal import verified_company_principal
from security_admin import current_role

# Field type = text, amount, date, currency, or company-scoped lookup section.
FORMS = {
    'Müşteri ekle': ('create_customer', [('name','Müşteri adı','text'),('country','Ülke','text'),('sector','Sektör','text'),('currency','Para birimi','currency')]),
    'İrtibat kişisi ekle': ('create_contact', [('customer_id','Müşteri','Müşteriler'),('name','Ad soyad','text'),('email','E-posta','text'),('phone','Telefon','text')]),
    'Depo ekle': ('create_warehouse', [('name','Depo adı','text'),('city','Şehir','text')]),
    'Ortak ürün kataloğuna ekle': ('create_product', [('name','Ürün adı','text'),('category','Kategori','text')]),
    'Banka / kasa aç': ('create_account', [('name','Hesap adı','text'),('currency','Para birimi','currency'),('opening_balance','Açılış bakiyesi','amount')]),
    'Satın alma siparişi': ('create_purchase_order', [('po_number','Sipariş numarası','text'),('supplier','Tedarikçi','text'),('product_id','Ürün','Ürünler'),('warehouse_id','Teslim deposu','Depolar'),('quantity_kg','Miktar (kg)','amount'),('unit_price','Birim alış fiyatı','amount'),('currency','Para birimi','currency')]),
    'Sevkiyat oluştur': ('create_shipment', [('purchase_order_id','Satın alma siparişi','Satın Alma'),('shipment_ref','Sevkiyat referansı','text'),('quantity_kg','Miktar (kg)','amount')]),
    'Sevkiyatı depoya al': ('receive_shipment', [('shipment_id','Sevkiyat','Sevkiyat')]),
    'Kalite blokajı': ('hold_inventory_lot', [('lot_id','Stok lotu','Stok'),('case_no','Uygunsuzluk numarası','text'),('hold_kg','Bloke miktar (kg)','amount'),('reason','Gerekçe','text')]),
    'Kalite blokajını kaldır': ('release_inventory_lot', [('lot_id','Stok lotu','Stok'),('resolution','Çözüm / değerlendirme','text')]),
    'Tedarikçi borcu kaydet': ('create_payable', [('purchase_order_id','Satın alma siparişi','Satın Alma'),('supplier','Tedarikçi','text'),('invoice_no','Fatura numarası','text'),('due_date','Vade','date'),('amount','Tutar','amount'),('currency','Para birimi','currency')]),
    'Müşteri alacağı kaydet': ('create_receivable', [('customer_id','Müşteri','Müşteriler'),('invoice_no','Fatura numarası','text'),('due_date','Vade','date'),('amount','Tutar','amount'),('currency','Para birimi','currency')]),
    'Tedarikçiye ödeme': ('pay_supplier', [('payable_id','Borç','Borçlar'),('account_id','Banka / kasa','Banka / Kasa'),('amount','Ödeme tutarı','amount'),('reference','Ödeme referansı','text'),('payment_date','Ödeme tarihi','date')]),
    'Müşteri tahsilatı': ('collect_customer_payment', [('receivable_id','Alacak','Alacaklar'),('account_id','Banka / kasa','Banka / Kasa'),('amount','Tahsilat tutarı','amount'),('reference','Tahsilat referansı','text'),('payment_date','Tahsilat tarihi','date')]),
}
MESSAGES = {
    'forbidden': 'Bu şirket veya işlem için yetkiniz bulunmuyor.',
    'connection_not_configured': 'Kullanıcıya özel güvenli veritabanı bağlantısı henüz yapılandırılmadı.',
    'unsafe_database_role': 'Veritabanı rolü veya şirket güvenlik kuralları hazır değil.',
    'identity_mismatch': 'Giriş hesabı ve veritabanı kullanıcı eşleştirmesi doğrulanamadı.',
    'read_only': 'Hesabınız salt okunur kullanımda.',
    'not_ready': 'Şirket veri yapısı henüz hazır değil.',
    'invalid_input': 'Alanları ve sayıların geçerliliğini kontrol edin.',
    'quality_hold_blocks_payment': 'Bu sipariş için açık kalite blokajı var; ödeme kaydedilmedi.',
    'overpayment': 'Ödeme açık borç tutarını aşıyor.',
    'over_collection': 'Tahsilat açık alacak tutarını aşıyor.',
    'insufficient_funds': 'Hesap bakiyesi yetersiz.',
    'currency_mismatch': 'İşlemin para birimi hesap veya siparişle uyuşmuyor.',
    'request_conflict': 'Önceki istekle farklı alanlar gönderildi. Yeni işlem başlatın.',
}


def _message(status):
    st.error(MESSAGES.get(status, 'İşlem tamamlanamadı. Kayıtları kontrol edip aynı isteği yeniden deneyebilirsiniz.'))


def _show(data):
    if isinstance(data, dict):
        counts = data['counts']
        for title, field in [('Sipariş','purchase_orders'),('Sevkiyat','shipments'),('Stok lotu','inventory_lots'),('Kalite dosyası','quality_cases')]:
            st.metric(title, counts[field])
        rows = [{'Gösterge': name, 'Para birimi': item['currency'], 'Tutar': str(item['amount'])}
                for name, items in data['finance_by_currency'].items() for item in items]
        st.dataframe(rows, width='stretch', hide_index=True)
    elif data:
        st.dataframe(data, width='stretch', hide_index=True)
    else:
        st.info('Bu şirkette kayıt bulunamadı.')


def render_company_runtime():
    st.title('AS Control Tower')
    if not verified_company_principal(st.session_state):
        st.error('Güvenli şirket oturumu doğrulanamadı. Hesabınızla tekrar giriş yapın.')
        return
    company = st.selectbox('Şirket', tuple(COMPANY_LABELS), format_func=COMPANY_LABELS.get, key='runtime_company')
    st.caption('Kayıtlar seçilen şirkete aittir. Ürün kataloğu dört şirket arasında ortaktır.')
    view = st.selectbox('Bölüm', ('Yönetici Özeti', *CRM_READ_SECTIONS, *OWNED_READ_SECTIONS, *EXTRA_READS), key='runtime_section')
    if st.button('Kayıtları getir', key='runtime_load'):
        status, data = execute_request(st.session_state, company, section=view)
        if status == 'ok':
            _show(data)
        else:
            _message(status)
    if runtime_mode() != WRITE_MODE or current_role() != 'ADMIN':
        st.info('Salt okunur kullanım: kayıt değiştirme kapalı.')
        return
    label = st.selectbox('Yeni işlem', tuple(FORMS), key='runtime_action')
    operation, fields = FORMS[label]
    # Context-specific keys prevent stale data crossing company or operation.
    context = company + ':' + operation
    if st.session_state.get('runtime_context') != context:
        for key in list(st.session_state):
            if key.startswith('runtime_field_'):
                del st.session_state[key]
        st.session_state['runtime_context'] = context
        st.session_state['runtime_request_id'] = str(uuid4())
        st.session_state.pop('runtime_done', None)
    if st.button('Yeni işlem başlat / alanları temizle', key='runtime_reset'):
        st.session_state.pop('runtime_context', None)
        st.rerun()
    # Resolve dependencies before the form; no credentials/IDs from other companies.
    lookups = {}
    for name, title, kind in fields:
        if kind not in ('text','amount','currency','date'):
            status, rows = execute_request(st.session_state, company, section=kind)
            if status != 'ok':
                _message(status)
                return
            if not rows:
                st.info(title + ' için önce kayıt oluşturun.')
                return
            lookups[name] = {r['id']: str(r['id'])+' · '+str(r.get('name') or r.get('po_number') or r.get('shipment_ref') or r.get('product_name') or r.get('invoice_no') or r.get('amount') or '') for r in rows}
    if st.session_state.get('runtime_done') == context:
        st.success('İşlem kaydedildi. Yeni kayıt için “Yeni işlem başlat” düğmesini kullanın.')
        return
    with st.form('runtime_operation_form'):
        inputs = {}
        for name, title, kind in fields:
            key = 'runtime_field_' + name
            if kind == 'text':
                inputs[name] = st.text_input(title, key=key)
            elif kind == 'amount':
                inputs[name] = st.number_input(title, min_value=0.0, value=0.0, format='%.4f', key=key)
            elif kind == 'currency':
                inputs[name] = st.selectbox(title, ('EUR','USD','GBP','TRY'), key=key)
            elif kind == 'date':
                inputs[name] = st.date_input(title, key=key).isoformat()
            else:
                inputs[name] = st.selectbox(title, tuple(lookups[name]), format_func=lookups[name].get, key=key)
        submitted = st.form_submit_button('Seçili şirkete kaydet', type='primary', width='stretch')
    if submitted:
        status, ident = execute_request(st.session_state, company, operation=operation,
                                       request_id=st.session_state['runtime_request_id'], inputs=inputs)
        if status == 'ok':
            st.session_state['runtime_done'] = context
            st.success(f'Kayıt tamamlandı. İşlem kaydı: {ident}')
        else:
            _message(status)
