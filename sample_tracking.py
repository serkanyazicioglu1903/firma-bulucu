"""Numune bilgi formu ve takip listesi: kayıtlar yalnızca açıkça kaydedilir."""
import json
from datetime import date, timedelta
import streamlit as st

STATUSES = ["Talep alındı", "Hazırlanıyor", "Gönderildi", "Teslim edildi", "Denemede", "Onaylandı", "Başarısız", "Siparişe dönüştü"]


def render_sample_tracking():
    st.header("🧪 Numune Takip")
    st.caption("Bu ilk sürüm yalnızca oturum içi takip içindir. Kalıcı kayıt ve şirket bazlı yetkilendirme henüz bağlı değildir.")
    if "sample_tracking_drafts" not in st.session_state:
        st.session_state["sample_tracking_drafts"] = []
    with st.form("sample_tracking_form", clear_on_submit=True):
        c1, c2 = st.columns(2)
        with c1:
            company = st.text_input("Müşteri firma *")
            contact = st.text_input("İlgili kişi")
            product = st.text_input("Ürün adı *")
            supplier = st.text_input("Üretici / tedarikçi")
            lot = st.text_input("Lot / parti numarası")
            quantity = st.number_input("Numune miktarı", min_value=0.0, step=0.1)
            unit = st.selectbox("Birim", ["kg", "g", "adet", "L", "mL"])
        with c2:
            sent = st.date_input("Gönderim tarihi", value=date.today())
            courier = st.text_input("Kargo firması")
            tracking = st.text_input("Kargo takip numarası")
            trial = st.date_input("Planlanan deneme / geri dönüş tarihi", value=date.today() + timedelta(days=14))
            application = st.text_input("Kullanım alanı / uygulama")
            status = st.selectbox("Durum", STATUSES)
            annual = st.text_input("Tahmini yıllık tüketim")
        notes = st.text_area("Deneme sonucu / notlar")
        saved = st.form_submit_button("Numune kaydını oturuma ekle", type="primary")
        if saved:
            if not company.strip() or not product.strip():
                st.error("Müşteri firma ve ürün adı zorunludur.")
            else:
                st.session_state["sample_tracking_drafts"].append({
                    "Firma": company.strip(), "Yetkili": contact.strip(),
                    "Ürün": product.strip(), "Üretici": supplier.strip(), "Lot": lot.strip(),
                    "Miktar": quantity, "Birim": unit, "Gönderim": sent.isoformat(),
                    "Kargo": courier.strip(), "Takip": tracking.strip(),
                    "Deneme tarihi": trial.isoformat(), "Uygulama": application.strip(),
                    "Durum": status, "Yıllık tüketim": annual.strip(), "Not": notes.strip(),
                })
                st.success("Numune taslağı bu oturuma eklendi.")
    records = st.session_state["sample_tracking_drafts"]
    if records:
        st.subheader("Numune takip listesi")
        st.dataframe(records, hide_index=True, width="stretch")
        overdue = [r for r in records if r["Deneme tarihi"] < date.today().isoformat() and r["Durum"] not in ("Onaylandı", "Başarısız", "Siparişe dönüştü")]
        st.metric("Geciken deneme / geri dönüş", len(overdue))
        st.download_button("Numune bilgi formlarını JSON indir", json.dumps(records, ensure_ascii=False, indent=2).encode("utf-8"), "numune_takip.json", "application/json")
