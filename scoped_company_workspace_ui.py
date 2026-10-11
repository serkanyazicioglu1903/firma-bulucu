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
from scripts.postgres_company_executive_snapshot import read_company_executive_snapshot


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
        "Operasyon bölümü", ("Yönetici Özeti", *tuple(OWNED_READ_SECTIONS)),
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
    if section == "Yönetici Özeti":
        status, report = read_company_executive_snapshot(url, principal, code)
        if status == "forbidden":
            st.error("Bu şirketin yönetici özetini görme izni tanımlı değil.")
        elif status == "not_ready":
            st.warning(
                "Şirket sahipliği ve kullanıcı izinleri doğrulanmadığı "
                "için şirket özeti gösterilmiyor."
            )
        elif status != "ok":
            st.error("Şirket bazlı özet güvenle hesaplanamadı.")
        else:
            st.caption(
                "Yalnızca yetkili olunan şirketin PostgreSQL kayıtlarından "
                "hesaplandı. CRM ortak kayıtları ve grup konsolidasyonu dahil değil."
            )
            counts = report["counts"]
            cols = st.columns(4)
            for col, (title, table) in zip(cols, (
                ("Sipariş", "purchase_orders"),
                ("Sevkiyat", "shipments"),
                ("Stok lotu", "inventory_lots"),
                ("Kalite dosyası", "quality_cases"),
            )):
                col.metric(title, counts[table])
            st.caption(
                f"Stok miktarı: {counts['inventory_quantity_kg']} kg | "
                f"Kalite blokajı: {counts['quality_hold_kg']} kg"
            )
            st.markdown("#### Şirket finansı — para birimi bazında")
            finance_labels = {
                "cash": "Banka / kasa bakiyesi",
                "receivables_open": "Açık alacak",
                "payables_open": "Açık borç",
            }
            currency_rows = [
                {
                    "Gösterge": finance_labels[name],
                    "Para birimi": item["currency"],
                    "Tutar": str(item["amount"]),
                }
                for name, values in report["finance_by_currency"].items()
                for item in values
            ]
            if currency_rows:
                st.dataframe(
                    pd.DataFrame.from_records(currency_rows),
                    width="stretch", hide_index=True,
                )
            else:
                st.info("Bu şirket için finansal tutar kaydı bulunamadı.")
            st.caption(
                "Farklı para birimleri toplanmadı, kur dönüşümü yapılmadı. "
                "Grup içi işlemler elimine edilmedi; konsolide kâr/zarar değildir."
            )
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
