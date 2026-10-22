
import re
import time
import json
import xml.etree.ElementTree as ET
from urllib.parse import urlparse, parse_qs, unquote, urljoin

import pandas as pd
import requests
import streamlit as st
from bs4 import BeautifulSoup

try:
    from ddgs import DDGS
except Exception:
    DDGS = None

from control_tower import render_control_tower
from four_company_demo import render_four_company_demo
from real_quote_workspace import render_real_quote_workspace
from security_admin import login_gate, logout_button
from scoped_company_workspace_ui import (
    company_review_mode_state, render_scoped_company_workspace,
)
from scripts.live_backend import postgres_url

st.set_page_config(
    page_title="AS İleri | Control Tower",
    page_icon="🏭",
    layout="wide",
    initial_sidebar_state="collapsed",
)

st.markdown(
    """
    <style>
    /* AS İleri premium shell */
    #MainMenu {visibility: hidden;}
    footer {visibility: hidden;}
    div[data-testid="stToolbar"] {visibility: hidden; height: 0;}
    div[data-testid="stDecoration"] {display: none;}

    .block-container {
        max-width: 1500px;
        padding-top: 1.4rem;
        padding-bottom: 3rem;
    }

    h1, h2, h3 {
        letter-spacing: -0.025em;
    }

    div[data-testid="stMetric"] {
        border: 1px solid rgba(128,128,128,.18);
        border-radius: 16px;
        padding: .85rem 1rem;
        background: rgba(255,255,255,.025);
    }

    div[data-testid="stDataFrame"] {
        border: 1px solid rgba(128,128,128,.14);
        border-radius: 14px;
        overflow: hidden;
    }

    .stButton > button,
    .stDownloadButton > button,
    div[data-testid="stFormSubmitButton"] > button {
        border-radius: 12px;
        min-height: 2.65rem;
        font-weight: 600;
    }

    div[data-baseweb="select"] > div,
    .stTextInput input,
    .stNumberInput input,
    .stTextArea textarea {
        border-radius: 12px !important;
    }

    /* Long multi-level navigation must remain reachable on a narrow phone.
       Keep the native Streamlit tab controls; do not hide inaccessible tabs. */
    div[data-baseweb="tab-list"] {
        gap: .25rem;
        flex-wrap: wrap !important;
        overflow-x: visible !important;
        height: auto !important;
        max-height: none !important;
    }
    div[data-testid="stTabs"] [data-baseweb="tab-list"] {
        display: flex !important;
        flex-wrap: wrap !important;
        align-items: stretch !important;
    }
    div[data-testid="stTabs"] [data-baseweb="tab"] {
        white-space: normal !important;
        overflow-wrap: anywhere !important;
        height: auto !important;
        min-height: 2.5rem !important;
        line-height: 1.25 !important;
    }
    @media (max-width: 768px) {
        div[data-testid="stTabs"] [data-baseweb="tab-list"] {
            gap: .2rem !important;
        }
        div[data-testid="stTabs"] [data-baseweb="tab"] {
            font-size: .78rem !important;
            padding: .4rem .5rem !important;
        }
    }

    button[data-baseweb="tab"] {
        border-radius: 10px 10px 0 0;
        padding-left: .65rem !important;
        padding-right: .65rem !important;
    }

    @media (max-width: 768px) {
        .block-container {
            padding-top: .7rem !important;
            padding-left: .9rem !important;
            padding-right: .9rem !important;
        }

        h1 {
            font-size: 2.15rem !important;
            line-height: 1.06 !important;
        }

        h2 {
            font-size: 1.65rem !important;
            line-height: 1.12 !important;
        }

        h3 {
            font-size: 1.32rem !important;
        }

        div[data-testid="stMetricValue"] {
            font-size: 2rem !important;
        }

        div[data-testid="stMetricLabel"] {
            font-size: .88rem !important;
        }

        button[data-baseweb="tab"] {
            font-size: .82rem !important;
            min-width: max-content;
        }

        div[data-testid="stDataFrame"] {
            font-size: .86rem;
        }

        .stButton > button,
        .stDownloadButton > button,
        div[data-testid="stFormSubmitButton"] > button {
            width: 100%;
        }
    }
    </style>
    """,
    unsafe_allow_html=True,
)

from scripts.company_runtime import runtime_mode
from company_runtime_ui import render_company_runtime

# Guard every tab, including supplier and acquisition searches. The previous
# Control Tower-only gate did not protect the rest of the application.
if not login_gate():
    st.stop()

if runtime_mode() != "disabled":
    if runtime_mode() == "invalid" or company_review_mode_state() != "disabled":
        st.error("Şirket çalışma modu geçersiz veya çelişkili; eski ekranlar kapalı.")
    else:
        logout_button()
        render_company_runtime()
    st.stop()
logout_button()

# Global, exclusive gate for the separately approved review-only mode.
# Without this, the two sourcing/acquisition tabs would still render next to
# the tenant-scoped Control Tower panel, bypassing the intended exclusive UI.
# This branch does not activate the flag; existing legacy mode is unchanged.
review_mode = company_review_mode_state()
if review_mode != "disabled":
    if review_mode != "review":
        st.error(
            "Dört şirket inceleme modu ayarı geçersiz veya çelişkili. "
            "Güvenlik gereği tüm eski ekranlar kapatıldı."
        )
        st.stop()
    url = postgres_url()
    if not url:
        st.error(
            "Şirket bazlı inceleme için doğrulanmış PostgreSQL bağlantısı "
            "gerekiyor. Eski ekranlar güvenlik nedeniyle açılmadı."
        )
        st.stop()
    st.warning(
        "Yalnızca imzalı kullanıcı oturumu ve veritabanı şirket izniyle "
        "salt okunur inceleme modu. Eski CRM, finans, tedarikçi arama, "
        "rapor ve dışa aktarma ekranları kapalı."
    )
    render_scoped_company_workspace(url)
    st.stop()

# =========================================================
# ORTAK AYARLAR
# =========================================================

from supplier_discovery import *  # Shared legacy/public research helpers

# =========================================================
# UI
# =========================================================

st.title("🏭 AS İleri – Firma & Ürün Bulucu")
st.caption("Şirket satın alma + yeni ürün / hammadde / üretici / distribütörlük araştırması tek uygulamada")

main_tab1, main_tab2, main_tab3, main_tab4, main_tab5 = st.tabs([
    "🏢 Firma Satın Alma / Halefiyet",
    "🧪 Satın Alma / Üretici Bulucu",
    "🧭 AS Control Tower",
    "🧮 Gerçek Teklif / Kârlılık",
    "🏢 Dört Şirket Demo",
])

# Streamlit evaluates ALL st.tabs panels on each rerun, even when hidden.
# Render the database-free quote FIRST so expensive legacy screens cannot
# prevent its widgets from appearing. Do NOT use st.page_link() here: the
# deployed Streamlit page registry can reject "pages/01_real_quote.py"
# and abort the whole app with StreamlitPageNotFoundError.
# The standalone route remains available through native multipage navigation.
with main_tab4:
    render_real_quote_workspace()

with main_tab5:
    render_four_company_demo()

# -------------------------
# TAB 1: ACQUISITION
# -------------------------
with main_tab1:
    st.subheader("Satılık firma / halefiyet araştırması")
    st.info(
        "Almanya için gıda hammaddesi, katkı maddeleri ve B2B özel kimyasal şirketlerini arar. "
        "Restoran, kafe, perakende, franchise ve pazar yeri sonuçlarını eler."
    )

    with st.expander("Almanya kaynakları ve arama yöntemi"):
        st.dataframe(
            pd.DataFrame(ACQ_SOURCE_GUIDE),
            width="stretch",
            hide_index=True,
            column_config={"URL": st.column_config.LinkColumn("Kaynak", display_text="Aç")},
        )
        st.caption(
            "Platform ilanları başlangıç noktasıdır. Uygun adaylar için IHK, banka, Steuerberater "
            "ve M&A danışmanı üzerinden ilan dışı (off-market) arama da yapılmalıdır."
        )

    c1, c2 = st.columns([1, 2])
    with c1:
        acq_countries = st.multiselect(
            "Ülkeler",
            list(ACQ_COUNTRIES),
            default=["Almanya", "İngiltere"],
            key="acq_countries",
        )
    with c2:
        acq_sectors = st.multiselect(
            "Sektörler",
            list(ACQ_SECTORS),
            default=["Gıda hammaddesi / Food ingredients", "Gıda katkı maddeleri", "Specialty chemicals"],
            key="acq_sectors",
        )

    col_a, col_b = st.columns(2)
    with col_a:
        acq_per_query = st.slider("Her sorguda sonuç", 3, 10, 5, key="acq_per_query")
    with col_b:
        acq_deep = st.checkbox("İlan sayfasını açıp finansal/iletişim bilgisi çıkar", value=True, key="acq_deep")

    if st.button("SATILIK FİRMA TARA", type="primary", width="stretch"):
        if not acq_countries or not acq_sectors:
            st.error("En az bir ülke ve sektör seçin.")
        else:
            st.session_state["acq_results"] = acq_scan(acq_countries, acq_sectors, acq_per_query, acq_deep)
            if st.session_state["acq_results"].empty:
                st.warning("Sıkı filtrelerden geçen aday bulunamadı.")
            else:
                st.success(f"{len(st.session_state['acq_results'])} aday bulundu.")

    acq_df = st.session_state.get("acq_results", pd.DataFrame())
    if not acq_df.empty:
        f1, f2, f3 = st.columns(3)
        with f1:
            min_score = st.slider("Minimum skor", 50, 100, 70, key="acq_min_score")
        with f2:
            only_sale = st.checkbox("Satış ilanı zorunlu", value=True, key="acq_sale")
        with f3:
            only_maker = st.checkbox("Üretim / operasyon sinyali zorunlu", value=False, key="acq_maker")

        view = acq_df[acq_df["Skor"] >= min_score].copy()
        if only_sale:
            view = view[view["Satış ilanı"] == "Evet"]
        if only_maker:
            view = view[view["Üretici sinyali"] == "Evet"]

        st.metric("Gösterilen ciddi aday", len(view))
        st.dataframe(
            view,
            width="stretch",
            hide_index=True,
            column_config={
                "İlan / kaynak URL": st.column_config.LinkColumn("İlan", display_text="Aç"),
                "Skor": st.column_config.ProgressColumn("Skor", min_value=0, max_value=100),
            },
        )
        st.download_button(
            "Satılık firma sonuçlarını CSV indir",
            view.to_csv(index=False).encode("utf-8-sig"),
            file_name="Satilik_Firma_Adaylari.csv",
            mime="text/csv",
            width="stretch",
        )

        st.divider()
        st.subheader("Seçilen firma için 12 soruluk ön değerlendirme")
        if view.empty:
            st.warning("Mevcut filtrelerle değerlendirilecek aday kalmadı. Minimum skoru düşürün.")
        else:
            selected_idx = st.selectbox(
                "Değerlendirilecek firma / ilan",
                options=view.index.tolist(),
                format_func=lambda idx: f"{view.loc[idx, 'Başlık']} · {view.loc[idx, 'Ülke']}",
                key="acq_review_candidate",
            )
            selected = view.loc[selected_idx]
            answers = []
            with st.expander("12 soruyu puanla: 0 = olumsuz/bilinmiyor, 1 = kısmen, 2 = olumlu", expanded=True):
                for number, (question, document, red_flag) in enumerate(ACQ_REVIEW_QUESTIONS, start=1):
                    left, right = st.columns([3, 1])
                    with left:
                        st.markdown(f"**{number}. {question}**")
                        st.caption(f"İstenecek belge: {document}  ·  Kırmızı bayrak: {red_flag}")
                    with right:
                        value = st.select_slider(
                            "Puan",
                            options=[0, 1, 2],
                            value=0,
                            key=f"acq_review_{selected_idx}_{number}",
                            label_visibility="collapsed",
                        )
                    answers.append(value)

            review_score = sum(answers)
            if review_score >= 18:
                review_result = "CİDDİ ADAY — LOI ve due diligence aşamasına geçilebilir."
                st.success(f"{review_score}/24 · {review_result}")
            elif review_score >= 12:
                review_result = "DİKKATLİ İLERLE — Zayıf noktalar fiyat ve sözleşmeye yansıtılmalı."
                st.warning(f"{review_score}/24 · {review_result}")
            else:
                review_result = "DUR — Bilgiler tamamlanmadan zaman ve inceleme maliyeti harcanmamalı."
                st.error(f"{review_score}/24 · {review_result}")

            assessment = {
                "firma_ilani": selected["Başlık"],
                "ulke": selected["Ülke"],
                "kaynak_url": selected["İlan / kaynak URL"],
                "puan": review_score,
                "sonuc": review_result,
                "cevaplar": [
                    {"soru": item[0], "puan": score, "istenecek_belge": item[1], "kirmizi_bayrak": item[2]}
                    for item, score in zip(ACQ_REVIEW_QUESTIONS, answers)
                ],
            }
            st.download_button(
                "Ön değerlendirmeyi JSON indir",
                json.dumps(assessment, ensure_ascii=False, indent=2).encode("utf-8"),
                file_name="Firma_On_Degerlendirme.json",
                mime="application/json",
                width="stretch",
            )

            if selected["Ülke"] == "Almanya":
                st.subheader("Hazır Almanca ilk temas taslağı")
                email_text = german_acquisition_email(selected["Başlık"], selected["İlan / kaynak URL"])
                st.text_area("E-posta", email_text, height=430, key=f"acq_mail_{selected_idx}")
                st.download_button(
                    "Almanca e-postayı indir",
                    email_text.encode("utf-8"),
                    file_name="Almanca_Ilk_Temas.txt",
                    mime="text/plain",
                    width="stretch",
                )

# -------------------------
# TAB 2: SOURCING / MANUFACTURER
# -------------------------
with main_tab2:
    st.subheader("Yeni ürün, hammadde, üretici ve temsilcilik araştırması")
    st.info("Sürüm 3 · Ücretli API kullanılmaz. Tarihli başlangıç kayıtları ile canlı arama adayları ayrı etiketlenir. Ücretsiz arama servisleri erişimi kısıtlayabilir; canlı adaylar ayrıca teyit gerektirir.")
    st.write(
        "Ürün adını yazın. Sistem üretici odaklı arama yapar, pazar yerlerini ve açık tüccar sonuçlarını eler; "
        "mümkünse resmi üretim sayfası, export/sales iletişimi ve Türkiye varlığını bulur."
    )

    q1, q2 = st.columns([2, 1])
    with q1:
        product = st.text_input(
            "Aranacak ürün / hammadde",
            placeholder="Örn: Vital Wheat Gluten, Dextrose Monohydrate, Topping Base, GMS, HPMC...",
            key="product_input",
        )
    with q2:
        source_country = st.selectbox("Hedef ülke / pazar", SOURCE_COUNTRIES, index=0, key="source_country")

    objective = st.multiselect(
        "Amaç",
        ["Hammadde satın alma", "Distribütörlük / temsilcilik", "Private label / fason üretim"],
        default=["Hammadde satın alma", "Distribütörlük / temsilcilik"],
        key="source_objective",
    )

    s1, s2, s3 = st.columns(3)
    with s1:
        max_companies = st.slider("Maksimum firma", 5, 20, 10, key="max_companies")
    with s2:
        supplier_deep = st.checkbox("Resmi siteyi açıp üretimi doğrulamaya çalış", value=True, key="supplier_deep")
    with s3:
        turkey_check = st.checkbox("Türkiye temsilci / distribütör varlığını kontrol et", value=True, key="turkey_check")

    sender_email = st.text_input(
        "Teklif isteme e-postasında dönüş adresi",
        value=st.session_state.get("sender_email", "serkan@asileri.com"),
        key="sender_email",
    )

    if st.button("ÜRÜN / ÜRETİCİ ARA", type="primary", width="stretch"):
        if not product.strip():
            st.error("Önce ürün veya hammadde adını yazın.")
        else:
            st.session_state["supplier_results"] = supplier_scan(
                product.strip(),
                source_country,
                objective,
                max_companies,
                supplier_deep,
                turkey_check,
            )
            if st.session_state["supplier_results"].empty:
                st.warning("Listelenecek üretici adayı bulunamadı. Bu, üretici olmadığı anlamına gelmez: arama servisine erişim, sayfa okuma veya filtreler nedeniyle sonuç alınamamış olabilir. Ürün adını İngilizce veya teknik adıyla deneyin.")
            else:
                st.success(f"{len(st.session_state['supplier_results'])} üretici adayı bulundu.")

    supplier_df = st.session_state.get("supplier_results", pd.DataFrame())
    if "supplier_diagnostics" in st.session_state:
        st.write("Arama özeti", st.session_state["supplier_diagnostics"])
        if st.session_state["supplier_diagnostics"]["Canlı üretici adayı"] == 0:
            st.warning("Canlı aramadan uygun yeni üretici adayı doğrulanamadı. Varsa aşağıdaki tarihli başlangıç kayıtları gösteriliyor; bu durum canlı aramanın başarılı olduğu anlamına gelmez.")
    if not supplier_df.empty:
        min_fit = st.slider("Minimum üretici uygunluk skoru", 0, 100, 0, key="supplier_min_fit")
        supplier_view = supplier_df[supplier_df["Fit Score"] >= min_fit].copy()

        st.metric("Gösterilen üretici adayı", len(supplier_view))
        st.dataframe(
            supplier_view.drop(columns=["Taslak E-mail"], errors="ignore"),
            width="stretch",
            hide_index=True,
            column_config={
                "Kaynak URL": st.column_config.LinkColumn("Kaynak", display_text="Aç"),
                "Website": st.column_config.LinkColumn("Website", display_text="Site"),
                "Üretim Kaynak URL": st.column_config.LinkColumn("Üretim kaynağı", display_text="Aç"),
                "İletişim URL": st.column_config.LinkColumn("İletişim", display_text="Aç"),
                "Fit Score": st.column_config.ProgressColumn("Fit Score", min_value=0, max_value=100),
            },
        )

        d1, d2 = st.columns(2)
        with d1:
            st.download_button(
                "Üretici sonuçlarını CSV indir",
                supplier_view.to_csv(index=False).encode("utf-8-sig"),
                file_name=f"Uretici_Adaylari_{re.sub(r'[^A-Za-z0-9]+','_',product)[:40]}.csv",
                mime="text/csv",
                width="stretch",
            )
        with d2:
            st.download_button(
                "Üretici sonuçlarını JSON indir",
                json.dumps(supplier_view.to_dict(orient="records"), ensure_ascii=False, indent=2).encode("utf-8"),
                file_name=f"Uretici_Adaylari_{re.sub(r'[^A-Za-z0-9]+','_',product)[:40]}.json",
                mime="application/json",
                width="stretch",
            )

        st.markdown("### ✉️ Firma bazında hazır teklif / temsilcilik e-postası")
        firms = supplier_view["Firma"].tolist()
        if firms:
            selected_index = st.selectbox("Firma seç", list(range(len(supplier_view))), format_func=lambda i: supplier_view.iloc[i]["Firma"], key="supplier_mail_index")
            selected_row = supplier_view.iloc[selected_index]
            draft_key = f"{selected_row['Kaynak URL']}:{selected_row['Taslak Konu']}"
            st.text_input("Konu", value=selected_row["Taslak Konu"], key=f"subject:{draft_key}")
            st.text_area("E-posta", value=selected_row["Taslak E-mail"], height=430, key=f"body:{draft_key}")
            st.caption("Bu bir taslaktır. Program e-posta göndermez. Sonuçları saklamak için CSV veya JSON indirin; oturum verileri kalıcı kayıt değildir.")
        else:
            st.info("Seçtiğiniz minimum skoru geçen firma yok. Daha düşük bir skor seçebilirsiniz.")

# -------------------------
# TAB 3: CONTROL TOWER
# -------------------------
with main_tab3:
    render_control_tower()

st.markdown("---")
st.caption(
    "Sistem bilinmeyen veriyi uydurmaz. Kamuya açık sayfaları kullanır; CAPTCHA/giriş engellerini aşmaz. "
    "Üretici doğrulaması otomatik bir ön elemedir; sipariş veya sözleşme öncesinde resmi belge ve ticari due diligence gerekir."
)
