"""Phone-friendly ADMIN-only preview of group companies and release blockers.

This deliberately is NOT a company selector: existing business screens are
not company-scoped. No user grant, database migration, backfill or financial
record is exposed, and no PostgreSQL read happens before the inspect click.
"""
import pandas as pd
import streamlit as st

from security_admin import current_role
from scripts.postgres_group_readiness import group_preview, evaluate_group_readiness


def render_group_readiness_quick(url):
    if current_role() != "ADMIN":
        return
    with st.expander("🏢 Grup Şirketleri — 4 şirket / canlı ayrım kontrolü"):
        preview = group_preview()
        st.caption(
            "Dört şirketin kurulu olduğu bildirildi. Bu liste yalnızca "
            "yönetim planıdır; sicil unvanları ve PostgreSQL şirket "
            "kimlikleri henüz doğrulanmadı."
        )
        st.dataframe(
            pd.DataFrame([
                {"Şirket": item["name"], "Durum": item["status"]}
                for item in preview["companies"]
            ]),
            width="stretch", hide_index=True,
        )
        st.warning(
            "Dört şirketin satın alma, stok, banka ve finans kayıtları "
            "henüz ayrı ve yetkilendirilmiş değil. Bu ekran şirket "
            "değiştirme yetkisi vermez. Mevcut diğer ekranlarda şirket "
            "filtresi varmış gibi işlem yapmayın ve gerçek toplu veri "
            "aktarmayın."
        )
        st.caption(
            "Holding toplulaştırması da aktif değildir: grup içi "
            "işlemlerin eliminasyonu ve kur/muhasebe kontrolleri gerekli."
        )
        if not st.button(
            "Şirket ayrımı için şema kontrolü yap (salt okunur)",
            key="ct_four_company_readiness_check",
        ):
            return
        if not url:
            st.error("PostgreSQL bağlantısı yapılandırılmamış.")
            return
        report = evaluate_group_readiness(url)
        if report["status"] == "failed":
            st.error("Şirket ayrımı kontrol edilemedi; canlı kullanım onayı yok.")
            return
        if report["missing_owner_tables"]:
            st.error(
                f"{report['checked_tables']} kritik operasyon/finans "
                f"tablosundan {report['missing_owner_tables']} tanesinde "
                "doğrudan şirket sahipliği alanı görünmüyor."
            )
        else:
            st.warning(
                "Şirket kimlik alanları görünse bile gerçek yetkilendirme, "
                "banka ayrımı, finans raporları ve geri yükleme testleri "
                "yapılmadı. Canlı kullanım onayı yok."
            )
        st.caption(
            "Bu kontrol PostgreSQL şema bilgilerini okur; müşteri, fiyat, "
            "banka bakiyesi veya başka şirket verisi göstermez."
        )
