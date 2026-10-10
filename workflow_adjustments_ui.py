"""Manager forms for explicit cost reconciliation, returns, and corrections."""
from datetime import date
import streamlit as st
import workflow_adjustments as adjustments


def result(outcome):
    ok,message=outcome
    if ok:
        st.session_state['workflow_adjustment_success']=message
        st.rerun()
    st.error(message)


def render_adjustments(orders):
    if st.session_state.get('workflow_adjustment_success'):
        st.success(st.session_state.pop('workflow_adjustment_success'))
    if orders.empty:
        return
    ct=adjustments.core()
    st.markdown('**Gerçekleşen maliyet ve düzeltmeler**')
    st.dataframe(adjustments.cost_report(),hide_index=True,width='stretch')
    st.caption('Mal bedeli dahil tüm gerçekleşen masrafları girin. Mutabakat kapanmadan gerçekleşen katkı gösterilmez. Masraf kaydı tek başına banka veya borç kaydı oluşturmaz.')
    costs_tab,return_tab,reverse_tab=st.tabs(['Gerçek maliyet / mutabakat','Müşteri iadesi','Finans ters kayıt'])
    with costs_tab:
        with st.form('actual_cost'):
            wid=st.selectbox('Maliyet siparişi',orders.id.tolist())
            category=st.selectbox('Masraf kategorisi',adjustments.CATEGORIES)
            reference=st.text_input('Masraf belge referansı')
            amount=st.number_input('Gerçekleşen tutar',min_value=0.0)
            currency=st.selectbox('Masraf para birimi',['EUR','USD','GBP','TRY'])
            fx=st.number_input('1 birim dövizin sipariş baz parasındaki değeri',min_value=0.000001,value=1.0,format='%.6f')
            day=st.date_input('Masraf belge tarihi')
            reason=st.text_input('Masraf açıklaması')
            if st.form_submit_button('Gerçek maliyeti kaydet'):
                result(adjustments.add_cost(wid,reference,category,amount,currency,fx,day,reason))
        with st.form('cost_reconcile'):
            wid=st.selectbox('Mutabakat siparişi',orders.id.tolist())
            closed=st.checkbox('Mal bedeli ve tüm ilgili masraflar tamamlandı; mutabakatı kapat')
            note=st.text_input('Mutabakat / yeniden açma açıklaması')
            if st.form_submit_button('Mutabakat durumunu kaydet'):
                result(adjustments.reconcile(wid,closed,note))
        costs=ct.query_df('SELECT * FROM workflow_costs ORDER BY id DESC')
        if not costs.empty:
            st.dataframe(costs,hide_index=True,width='stretch')
            with st.form('reverse_cost'):
                cost_id=st.selectbox('Ters kaydedilecek masraf',costs.loc[costs.amount>0,'id'].tolist())
                reference=st.text_input('Masraf ters kayıt referansı')
                reason=st.text_input('Masraf düzeltme gerekçesi')
                if st.form_submit_button('Masrafı ters kaydet'):
                    result(adjustments.reverse_cost(cost_id,reference,reason))
    with return_tab:
        deliveries=ct.query_df('SELECT id,reference,quantity_kg FROM workflow_deliveries ORDER BY id DESC')
        st.caption('İade, ayrı bir HOLD lotu açar. Tahsil edilmiş kısım varsa Finans bölümünde müşteriye geri ödeme borcu oluşur. Otomatik banka transferi yapılmaz.')
        if deliveries.empty:
            st.info('İade için önce müşteri sevki kaydedilmeli.')
        else:
            with st.form('customer_return'):
                did=st.selectbox('İade edilen teslimat',deliveries.id.tolist(),format_func=lambda x:f'#{x} · {deliveries.set_index("id").loc[x,"reference"]}')
                qty=st.number_input('İade miktarı (kg)',min_value=0.0)
                reference=st.text_input('İade belge referansı')
                day=st.date_input('İade tarihi')
                reason=st.text_input('İade gerekçesi')
                if st.form_submit_button('İadeyi ve alacak mahsubunu kaydet'):
                    result(adjustments.return_delivery(did,qty,reference,day,reason))
        st.dataframe(ct.query_df('SELECT * FROM workflow_returns ORDER BY id DESC'),hide_index=True,width='stretch')
    with reverse_tab:
        tx=ct.query_df("SELECT id,transaction_type,amount,currency,reference FROM finance_transactions WHERE amount>0 AND transaction_type IN ('Tahsilat','Ödeme') ORDER BY id DESC")
        st.caption('Yalnız hatalı kaydı düzeltmek için kullanın. Asıl hareket silinmez; ters kayıt banka ve cari bakiyeyi birlikte düzeltir. Gerçek müşteri geri ödemesi için iade borcunu ödeyin.')
        if not tx.empty:
            st.dataframe(tx,hide_index=True,width='stretch')
            with st.form('reverse_payment'):
                tid=st.selectbox('Düzeltilecek finans hareketi',tx.id.tolist())
                reference=st.text_input('Finans ters kayıt referansı')
                reason=st.text_input('Finans düzeltme gerekçesi')
                confirmed=st.checkbox('Seçili hareketin hatalı kayıt olduğunu doğruluyorum')
                if st.form_submit_button('Finans hareketini ters kaydet'):
                    if confirmed:
                        result(adjustments.reverse_payment(tid,reference,reason))
                    else:
                        st.error('Önce hatalı kayıt doğrulamasını işaretleyin.')
