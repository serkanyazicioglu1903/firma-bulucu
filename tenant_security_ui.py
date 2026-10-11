"""ADMIN-only mobile-friendly security truth panel; read-only on click."""
import streamlit as st

from security_admin import current_role
from scripts.postgres_tenant_security_preflight import (
    inspect_company_access_security,
)


def render_company_access_security_quick(url):
    if current_role() != "ADMIN":
        return
    with st.expander("🔐 Dört şirket — RLS ve gerçek API izinleri"):
        st.caption(
            "Bu kontrol yalnızca PostgreSQL güvenlik metadata'sını okur. "
            "Müşteri, banka, tutar veya parola göstermez; hiçbir izin değiştirmez."
        )
        if not st.button(
            "RLS ve API izinlerini denetle (salt okunur)",
            key="ct_tenant_security_review",
        ):
            return
        if not url:
            st.error("PostgreSQL bağlantısı yapılandırılmamış.")
            return
        result = inspect_company_access_security(url)
        if result["status"] in ("failed", "invalid_url"):
            st.error("Güvenlik durumu güvenle okunamadı. Canlı geçiş engellendi.")
            return

        st.caption(
            f"Tablo: {result['total_tables']} | RLS açık: {result['rls_enabled']} "
            f"| Şirket sahiplik alanı: {result['owner_columns']}/8 "
            f"| Şirket/izin tabloları: {result['registry_tables']}/5"
        )
        role_names = {
            "anon": "Anonim API",
            "authenticated": "Giriş yapılmış API",
            "service_role": "Servis API rolü",
        }
        for name, friendly in role_names.items():
            count = result["api_direct_access"][name]
            writes = result["api_direct_writes"][name]
            st.caption(
                f"{friendly}: doğrudan erişilebilir tablo {count}; "
                f"yazma izni bulunan tablo {writes}"
            )
        if result["status"] == "api_permissions_review":
            st.error(
                "API rolü için ct_app üzerinde doğrudan tablo izni tespit "
                "edildi. RLS ve izin kapsamı denetlenmeden işlem yapılamaz."
            )
        else:
            st.warning(
                "İncelenen üç API rolünde doğrudan tablo erişim izni "
                "tespit edilmedi. Ancak bu durum diğer veritabanı rolleri "
                "ve eski uygulama yollarının güvenli olduğunu kanıtlamaz."
            )
        if result["rls_enabled"] < result["total_tables"]:
            st.warning(
                "RLS bütün uygulama tablolarında açık değil. Politika ve "
                "rol planı olmadan RLS otomatik etkinleştirilmez."
            )
        if result["current_session_elevated"]:
            st.warning(
                "Kullanılan veritabanı oturumu yüksek yetkili olabilir; "
                "RLS atlama ve en az yetki ilkesi ayrıca incelenmeli."
            )
        st.error(
            "Dört şirketin canlıya geçişi ONAYLI DEĞİL. Gerçek şirket "
            "kayıtları, tüm iş ekranlarının izolasyonu ve bağımsız gerçek "
            "Supabase yedeğinin geri yüklenmesi henüz doğrulanmadı."
        )
