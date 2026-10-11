"""ADMIN-only 26-table ownership/visibility review, never a live migration.

The button asks the server for fixed pg_catalog metadata only. This is a
separate snapshot from API-privilege review and never claims user-level access
is safe or any real record has an approved legal owner.
"""
import streamlit as st

from security_admin import current_role
from scripts.postgres_company_full_coverage import (
    REVIEW_GROUPS, inspect_live_company_ownership,
)

_GROUP_TITLES = {
    "direct_owner_required": "Tüzel kişi alanı zorunlu",
    "shared_master_decision": "Ortak ürün verisi kararı bekliyor",
    "parent_ownership_decision": "Müşteri / depo / görev sahipliği kararı",
    "derived_ownership_decision": "Bağlı operasyon / CRM kayıtları",
    "internal_access_decision": "Yönetim / denetim erişim kararı",
}


def render_company_ownership_coverage_quick(url):
    """Never run against DB for non-ADMIN or without an explicit button click."""
    if current_role() != "ADMIN":
        return
    with st.expander("🏢 Dört şirket — 26 tablo sahiplik kontrolü"):
        st.caption(
            "Salt okunur yapı denetimi. Sadece tablo adları ve PostgreSQL "
            "kolon bilgileri incelenir; hiçbir şirket kaydı veya tutarı okunmaz."
        )
        if not st.button(
            "26 tablonun şirket ayrımı eksiklerini denetle",
            key="ct_company_26table_ownership_check",
        ):
            return
        if not url:
            st.error("PostgreSQL bağlantısı yapılandırılmamış. İnceleme durduruldu.")
            return
        result = inspect_live_company_ownership(url)
        if result["status"] in (
            "failed", "invalid_url", "invalid_inventory",
            "schema_mismatch", "invalid_metadata",
        ):
            st.error(
                "26 tablonun tamamı güvenle doğrulanamadı; "
                "şirket ayrımı ve canlı geçiş engellendi."
            )
            return

        st.caption(
            f"Kontrol edilen: {result['table_count']}/26 tablo | "
            f"RLS açık: {result['rls_enabled_count']}/26 | "
            f"Doğrudan sahiplik alanı: {result['direct_owner_count']}/26 | "
            f"Zorunlu ve NOT NULL: "
            f"{result['required_nonnull_owner_count']}/8"
        )
        if result["missing_required_owner"]:
            st.warning(
                "Şirket sahiplik kolonu eksik: "
                + ", ".join(result["missing_required_owner"])
            )
        if result["nullable_required_owner"]:
            st.warning(
                "Şirketi belirtilmemiş kayıtlara izin verebilecek alanlar: "
                + ", ".join(result["nullable_required_owner"])
            )

        st.markdown("**26 tablo için ayrı değerlendirme kapsamı**")
        for group, title in _GROUP_TITLES.items():
            st.caption(
                f"{title} ({len(REVIEW_GROUPS[group])}): "
                + ", ".join(REVIEW_GROUPS[group])
            )
        st.warning(
            "Diğer 18 tablonun şirket bazlı görünürlüğü ve ilişkileri "
            "ayrıca tasarlanıp doğrulanmalı. Ortak müşteri / ürün verisi "
            "otomatik olarak güvenli veya şirketler arası paylaşılabilir sayılmaz."
        )
        st.error(
            "Dört şirket için canlı yetkilendirme ONAYLI DEĞİL. "
            "Gerçek kayıt sahipliği, tüm kullanıcı/rol yolları, finans mutabakatı, "
            "bağımsız güncel yedek ve geri yükleme henüz onaylanmadı."
        )
