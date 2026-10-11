"""Opt-in, read-only company-scoped PostgreSQL viewer.

Never render existing unscoped legacy finance, bank, CRM, imports, reports or
transaction screens in this review mode. It is OFF by default and requires
a signed authenticated session plus DB-granted exact legal-entity ownership.
Not a completed production four-company rollout.
"""
import os

import pandas as pd
import streamlit as st

from scripts.group_company_catalog import COMPANY_LABELS
from scripts.postgres_scoped_company_read import (
    OWNED_READ_SECTIONS, read_company_records,
)
from scripts.company_session_principal import verified_company_principal


MODE_SECRET = "CT_COMPANY_SCOPED_VIEW_MODE"
REVIEW_MODE = "REVIEW_ONLY_WITH_SIGNED_SESSION"


def scoped_company_view_enabled():
    """An explicit reviewer-activated mode, NOT enabled by this PR."""
    try:
        setting = st.secrets.get(MODE_SECRET, "")
    except Exception:
        setting = ""
    setting = setting or os.environ.get(MODE_SECRET, "")
    return isinstance(setting, str) and setting == REVIEW_MODE


def render_scoped_company_workspace(url):
    """Scoped read only. No other legacy admin widgets are reachable here."""
    st.subheader("🏢 Şirket Bazlı Operasyonlar — Güvenli İnceleme")
    st.warning(
        "Bu mod yalnızca kayıtları görüntüler. Çok şirketli muhasebe, "
        "CRM, stok hareketi, para transferi, içe aktarım, toplu rapor ve "
        "konsolidasyon henüz üretim kullanımına onaylanmadı."
    )
    principal = verified_company_principal(st.session_state)
    if not principal:
        st.error(
            "Şirket görüntülemesi için doğrulanmış kullanıcı oturumu yok. "
            "APP_USERS_JSON ve ayrı sunucu oturum imza ayarları gözden "
            "geçirilmeli; yetkili kullanıcı tekrar giriş yapmalı."
        )
        return
    code = st.selectbox(
        "Şirket", tuple(COMPANY_LABELS),
        format_func=lambda item: COMPANY_LABELS[item],
        key="ct_signed_company_code",
    )
    section = st.selectbox(
        "Operasyon bölümü", tuple(OWNED_READ_SECTIONS),
        key="ct_signed_company_section",
    )
    st.caption(
        "Her seçimde, sunucunun doğruladığı kullanıcı ve veritabanındaki "
        "açık şirket izni tekrar kontrol edilir. Şirket seçmek erişim "
        "yetkisi vermez."
    )
    if not st.button(
        "Seçili şirkete ait kayıtları güvenli getir",
        key="ct_signed_company_load",
    ):
        return
    status, rows = read_company_records(url, principal, code, section)
    if status == "forbidden":
        st.error("Bu şirket için kayıt görüntüleme izni tanımlanmamış.")
    elif status == "not_ready":
        st.warning(
            "Şirket sahipliği alanları ve izin tabloları henüz canlı "
            "veritabanında tam ve doğrulanmış değil. Veri gösterilmiyor."
        )
    elif status != "ok":
        st.error("Güvenli veri sorgusu doğrulanamadı; kayıt gösterilmiyor.")
    elif rows:
        st.caption(
            "Yalnızca seçilen şirketin yetkili, en fazla 100 kaydı "
            "gösteriliyor. Kayıt değiştirilmedi."
        )
        st.dataframe(pd.DataFrame.from_records(rows), width="stretch", hide_index=True)
    else:
        st.info("Bu şirkette seçilen bölüm için kayıt bulunamadı.")
