"""Numune bilgi formu ve takip listesi: kayıtlar yalnızca açıkça kaydedilir."""
import json
from datetime import date, timedelta
import streamlit as st
from sample_pdf import make_sample_pdf
from sample_backup import parse_sample_backup
from sample_reporting import filter_samples, sample_summary, samples_csv
from scripts.sample_persistence_readiness import sample_persistence_readiness_on_cursor
from scripts.live_backend import postgres_url

STATUSES = ["Talep alındı", "Hazırlanıyor", "Gönderildi", "Teslim edildi", "Denemede", "Onaylandı", "Başarısız", "Siparişe dönüştü"]


def render_sample_tracking():
    st.header("🧪 Numune Takip")
    st.caption("Numuneler hâlâ oturumda tutulur; kalıcı kayıt yalnızca güvenli şirket yetkileri doğrulandıktan sonra açılacaktır.")
    with st.expander("🔐 Kalıcı kayıt güvenlik durumu", expanded=False):
        url = postgres_url()
        if not url or url == "INVALID_POSTGRES_URL":
            st.warning("Doğrulanmış PostgreSQL bağlantısı bulunamadı. Kalıcı kayıt kapalı.")
        else:
            try:
                import psycopg
                from scripts.postgres_connection import sslmode_for
                with psycopg.connect(url, sslmode=sslmode_for(url), connect_timeout=5) as connection:
                    with connection.cursor() as cursor:
                        status = sample_persistence_readiness_on_cursor(cursor)
                if status["ready"]:
                    st.info("Şema güvenlik önkoşulları mevcut. Kullanıcı izinleri ve uçtan uca yazma testleri henüz tamamlanmadığından kalıcı kayıt kapalı.")
                else:
                    st.warning("Canlı veritabanında numune kayıtlarının güvenli şirket ayrımı henüz hazır değil. Kalıcı kayıt kapalı.")
                    st.caption("Eksik güvenlik tabloları: " + ", ".join(status["missing"]) if status["missing"] else "Eksik güvenlik tablosu yok.")
                    if status["rls_not_forced"]:
                        st.caption("Zorunlu RLS eksik: " + ", ".join(status["rls_not_forced"]))
            except Exception:
                st.warning("Güvenlik kontrolü tamamlanamadı. Kalıcı kayıt kapalı.")
    if "sample_tracking_drafts" not in st.session_state:
        st.session_state["sample_tracking_drafts"] = []
    with st.expander("📥 Önceki oturumdan numune kayıtlarını geri yükle"):
        st.warning("Yalnızca daha önce bu ekrandan indirdiğiniz JSON dosyasını kullanın. "
                   "Yükleme mevcut oturum listesini değiştirir; veritabanına yazmaz.")
        uploaded = st.file_uploader("Numune JSON dosyası", type=["json"], key="sample_restore_file")
        confirmed = st.checkbox("Mevcut oturum listesini değiştirmeyi onaylıyorum",
                                key="sample_restore_confirm")
        if st.button("Dosyadaki kayıtları oturuma yükle", disabled=not (uploaded and confirmed)):
            try:
                restored = parse_sample_backup(uploaded.getvalue())
            except ValueError:
                st.error("Dosya geçersiz veya desteklenen numune kayıt biçiminde değil.")
            else:
                st.session_state["sample_tracking_drafts"] = restored
                st.success(f"{len(restored)} kayıt oturuma yüklendi. Kalıcı kaydedilmedi.")
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
        metrics = sample_summary(records)
        m1, m2, m3, m4 = st.columns(4)
        m1.metric("Toplam numune", metrics["total"])
        m2.metric("Geciken takip", metrics["overdue"])
        m3.metric("Denemede", metrics["in_trial"])
        m4.metric("Onaylanan", metrics["approved"])

        search = st.text_input("Firma, ürün veya ilgili kişi ara", key="sample_filter_search")
        f1, f2, f3 = st.columns(3)
        with f1:
            status_filter = st.selectbox("Durum filtresi", ["Tümü"] + STATUSES,
                                         key="sample_filter_status")
        with f2:
            suppliers = sorted({r.get("Üretici", "").strip() for r in records
                                if r.get("Üretici", "").strip()})
            supplier_filter = st.selectbox("Üretici filtresi", ["Tümü"] + suppliers,
                                           key="sample_filter_supplier")
        with f3:
            overdue_only = st.checkbox("Yalnızca gecikenler", key="sample_filter_overdue")
        visible_indices = filter_samples(records, search=search, status=status_filter,
                                         supplier=supplier_filter, overdue_only=overdue_only)
        visible = [records[i] for i in visible_indices]
        st.caption(f"{len(visible)} / {len(records)} numune gösteriliyor.")
        if not visible:
            st.info("Bu filtrelerle eşleşen numune yok.")
        else:
            st.dataframe(visible, hide_index=True, width="stretch")
        st.download_button("Tüm numuneleri JSON indir",
                           json.dumps(records, ensure_ascii=False, indent=2).encode("utf-8"),
                           "numune_takip.json", "application/json")
        st.download_button("Filtrelenen numuneleri Excel uyumlu CSV indir",
                           samples_csv(visible), "numune_takip_filtreli.csv", "text/csv")
        if visible_indices:
            selected = st.selectbox("Bilgi formu / durum güncelleme için numune seç", visible_indices,
                                format_func=lambda i: f'{i+1} · {records[i]["Firma"]} · {records[i]["Ürün"]}')
            record = records[selected]
                st.download_button("📄 Numune bilgi formu PDF indir", make_sample_pdf(record),
                               file_name=f"numune_bilgi_formu_{selected+1}.pdf", mime="application/pdf")
            with st.form("sample_update_form"):
                new_status = st.selectbox("Güncel durum", STATUSES,
                                          index=STATUSES.index(record["Durum"]) if record["Durum"] in STATUSES else 0)
                new_notes = st.text_area("Deneme sonucu / takip notları", value=record["Not"])
                new_trial = st.date_input("Yeni deneme / geri dönüş tarihi",
                                          value=date.fromisoformat(record["Deneme tarihi"]))
                if st.form_submit_button("Durumu ve notları güncelle"):
                    record["Durum"] = new_status
                    record["Not"] = new_notes.strip()
                    record["Deneme tarihi"] = new_trial.isoformat()
                    st.success("Oturumdaki numune kaydı güncellendi.")
