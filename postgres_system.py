"""Admin-only PostgreSQL maintenance with simple mobile-friendly navigation.

Avoid nested Streamlit tabs inside the already deeply nested Control Tower
navigation. A separate quick backup shortcut is accessible above the main tabs
when the mobile System tab fails to display its body.
"""
from datetime import datetime, timezone

import pandas as pd
import streamlit as st

from scripts.postgres_compat import pg_query_df
from scripts.postgres_operational_read import read_operational_counts
from security_admin import current_role, current_user


def _render_backup(url, key_prefix):
    st.warning(
        "Bu yedek müşteri ve finans kayıtlarını içerebilir. "
        "İndirilen ZIP şifreli değildir; yalnızca güvenli ve şifreli "
        "bir depoda saklayın. Supabase otomatik yedek ve geri yükleme "
        "ayarlarını ayrıca doğrulayın."
    )
    if st.button(
        "Tutarlı PostgreSQL yedeği hazırla",
        key=f"{key_prefix}_prepare",
    ):
        from scripts.postgres_backup import export_postgres_backup

        with st.spinner("26 PostgreSQL tablosu salt okunur yedekleniyor..."):
            status, archive = export_postgres_backup(url)
        if status != "ok":
            st.error("Yedek hazırlanamadı; şema, bağlantı veya boyut sınırını kontrol edin.")
            return
        filename = (
            "AS_Control_Tower_ct_app_"
            + datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
            + ".zip"
        )
        st.success("Yedek hazır. Aşağıdaki düğmeden hemen indirin.")
        st.download_button(
            "💾 PostgreSQL yedeğini indir (özel şirket verisi)",
            data=archive,
            file_name=filename,
            mime="application/zip",
            key=f"{key_prefix}_download",
        )
        st.caption(
            "Dosya yalnızca bu işlem sırasında oturum belleğinde tutulur. "
            "Yedek dosyasını sohbet veya açık paylaşım bağlantısıyla göndermeyin."
        )


def render_postgres_quick_backup(url):
    """Secondary ADMIN-only maintenance entry independent of nested tabs."""
    if current_role() != "ADMIN":
        return
    with st.expander("💾 PostgreSQL yedekleme — hızlı erişim", expanded=False):
        st.caption(
            "Sistem sekmesi telefonda boş görünürse yedeği doğrudan "
            "buradan hazırlayıp indirebilirsiniz."
        )
        _render_backup(url, "ct_pg_quick_backup")


def _render_reconciliation(url, button_key):

    st.markdown("#### 🔍 Satın Alma, Stok, Kalite ve Finans Kontrolü")
    st.caption(
        "Supabase ct_app üzerinde 10 farklı tutarlılık kuralını "
        "yalnızca okuyarak denetler. Sipariş veya finans kaydı oluşturmaz, "
        "değiştirmez ve silmez. Firma detayları gösterilmez."
    )
    if st.button(
        "İş akışlarının tutarlılığını kontrol et",
        key=button_key,
    ):
        from scripts.postgres_reconciliation import (
            check_operational_consistency,
        )
        with st.spinner("İş akışları salt okunur kontrol ediliyor..."):
            result = check_operational_consistency(url)
        status = result["status"]
        if status not in ("ok", "issues_found"):
            st.error(
                "Kontrol tamamlanamadı. PostgreSQL bağlantısı ve "
                "ct_app şemasını doğrulayın. Hiçbir kayıt değiştirilmedi."
            )
        else:
            checks = result["checks"]
            total_critical = sum(
                item["count"] for item in checks
                if item["severity"] == "critical"
            )
            total_warnings = sum(
                item["count"] for item in checks
                if item["severity"] == "warning"
            )
            if total_critical:
                st.error(
                    f"{total_critical} kritik tutarsızlık tespit edildi. "
                    "Gerçek stok ve finans işlemlerine devam etmeden "
                    "kayıtları yetkili kullanıcıyla inceleyin."
                )
            elif total_warnings:
                st.warning(
                    f"{total_warnings} uyarı bulundu. Örneğin kredili "
                    "banka hesabında negatif bakiye normal olabilir."
                )
            else:
                st.success(
                    "10 kontrolde tutarsızlık bulunmadı. Bu sonuç yalnızca "
                    "incelenen kuralları doğrular; tam muhasebe mutabakatı "
                    "veya yedekten geri yükleme testi değildir."
                )
            st.dataframe(
                pd.DataFrame([
                    {
                        "Bölüm": item["area"],
                        "Kontrol": item["label"],
                        "Seviye": (
                            "Kritik" if item["severity"] == "critical"
                            else "Uyarı"
                        ),
                        "Sorun sayısı": item["count"],
                    }
                    for item in checks
                ]),
                width="stretch",
                hide_index=True,
            )
    st.info(
        "Yalnızca özet adetler gösterilir. Sorun bulunursa bu araç "
        "otomatik düzeltme yapmaz; kayıtların yetkili incelemesi gerekir."
    )



def render_postgres_quick_reconciliation(url):
    """ADMIN-only read-only control reachable above mobile tab navigation."""
    if current_role() != "ADMIN":
        return
    with st.expander("🔍 Operasyon Mutabakatı — hızlı erişim", expanded=False):
        _render_reconciliation(url, "ct_pg_quick_reconciliation_run")


def render_postgres_system(url):
    st.markdown("### ⚙️ Sistem Yönetimi — PostgreSQL")
    if current_role() != "ADMIN":
        st.error("Sistem yönetimi için ADMIN yetkisi gerekir.")
        return
    username = (current_user() or {}).get("username", "admin")
    st.caption(f"Aktif kullanıcı: {username} · veritabanı: Supabase ct_app")
    st.success("PostgreSQL kalıcı kayıt modu. SQLite iş verileri kullanılmıyor.")

    # A plain selectbox is intentionally more reliable than nested st.tabs
    # inside a 15-tab application on the narrow iPhone browser.
    section = st.selectbox(
        "Sistem bölümü",
        [
            "💾 Yedekleme",
            "🩺 Sistem Sağlığı",
            "🔍 Operasyon Mutabakatı",
            "🧾 Audit Log",
            "👥 Rol Yapısı",
        ],
        key="ct_pg_system_section",
    )

    if section == "💾 Yedekleme":
        st.markdown("#### 💾 PostgreSQL Yedekleme")
        _render_backup(url, "ct_pg_system_backup")

    elif section == "🩺 Sistem Sağlığı":
        st.info(
            "PostgreSQL bağlantısı TLS kullanır; iş kayıtları ct_app "
            "şemasında tutulur. Bağlantı parolası görüntülenmez."
        )
        if st.button(
            "Canlı PostgreSQL sayımlarını doğrula",
            key="ct_pg_system_health",
        ):
            status, counts = read_operational_counts(url)
            if status == "ok":
                st.success("PostgreSQL şeması ve operasyon tabloları okunuyor.")
                st.dataframe(
                    pd.DataFrame(
                        [{"Tablo": name, "Kayıt": n} for name, n in counts.items()]
                    ),
                    width="stretch",
                    hide_index=True,
                )
            else:
                st.error("PostgreSQL sağlık kontrolü başarısız; SQLite'a geçilmedi.")

    elif section == "🔍 Operasyon Mutabakatı":
        _render_reconciliation(url, "ct_pg_reconciliation_run")

    elif section == "🧾 Audit Log":
        st.caption("Yalnızca PostgreSQL ct_app denetim kayıtları gösterilir.")
        if st.button(
            "Son denetim kayıtlarını getir",
            key="ct_pg_system_audit_refresh",
        ):
            try:
                audits = pg_query_df(
                    url,
                    "SELECT created_at, username, role, action, table_name "
                    "FROM audit_log ORDER BY id DESC LIMIT 200",
                )
                st.dataframe(audits, width="stretch", hide_index=True)
            except Exception:
                st.error("PostgreSQL denetim kayıtları okunamadı.")

    elif section == "👥 Rol Yapısı":
        st.markdown(
            "**ADMIN:** Yönetim ve tüm iş modülleri.  "
            "**SALES:** CRM ve satış.  "
            "**PURCHASING:** Ürün, PO ve stok.  "
            "**QUALITY:** Kalite ve regülasyon.  "
            "**FINANCE:** Finans ve nakit.  "
            "**VIEWER:** Salt okunur yönetim."
        )
        st.caption(
            "Kullanıcı yetkileri sunucudaki APP_USERS_JSON "
            "veya CONTROL_TOWER_PASSWORD ayarlarından gelir."
        )
