"""PostgreSQL-only administration, audit and manually initiated backup tools."""
from datetime import datetime, timezone

import pandas as pd
import streamlit as st

from scripts.postgres_compat import pg_query_df
from scripts.postgres_operational_read import read_operational_counts
from security_admin import current_role, current_user


def render_postgres_system(url):
    st.markdown("### ⚙️ Sistem Yönetimi — PostgreSQL")
    if current_role() != "ADMIN":
        st.error("Sistem yönetimi için ADMIN yetkisi gerekir.")
        return
    username = (current_user() or {}).get("username", "admin")
    st.caption(f"Aktif kullanıcı: {username} · veritabanı: Supabase ct_app")
    st.success("PostgreSQL kalıcı kayıt modu. SQLite iş verileri kullanılmıyor.")

    health, audit, backup, roles = st.tabs(
        ["🩺 Sistem Sağlığı", "🧾 Audit Log", "💾 Yedekleme", "👥 Rol Yapısı"]
    )
    with health:
        st.info(
            "PostgreSQL bağlantısı şifreli TLS kullanır; iş verileri ct_app "
            "şemasında tutulur. Bağlantı parolası görüntülenmez."
        )
        if st.button("Canlı PostgreSQL sayımlarını doğrula", key="pg_live_health"):
            status, counts = read_operational_counts(url)
            if status == "ok":
                st.success("PostgreSQL şeması ve operasyon tabloları okunuyor.")
                st.dataframe(
                    pd.DataFrame(
                        [{"Tablo": name, "Kayıt": n} for name, n in counts.items()]
                    ),
                    width="stretch", hide_index=True,
                )
            else:
                st.error(
                    "PostgreSQL sağlık kontrolü başarısız. "
                    "Uygulama SQLite'a geçiş yapmadı."
                )

    with audit:
        st.caption("Yalnızca PostgreSQL ct_app audit kayıtları gösterilir.")
        if st.button("Son denetim kayıtlarını getir", key="pg_audit_refresh"):
            try:
                audits = pg_query_df(
                    url,
                    "SELECT created_at, username, role, action, table_name "
                    "FROM audit_log ORDER BY id DESC LIMIT 200",
                )
                st.dataframe(audits, width="stretch", hide_index=True)
            except Exception:
                st.error("PostgreSQL denetim kayıtları okunamadı.")

    with backup:
        st.warning(
            "Supabase otomatik yedekleme ve geri yükleme ayarlarını ayrıca "
            "doğrulayın. Aşağıdaki manuel yedek yalnızca indirilir; "
            "şifreli saklama sorumluluğu kullanıcıdadır."
        )
        if st.button("Tutarlı PostgreSQL yedeği hazırla", key="pg_backup_prepare"):
            from scripts.postgres_backup import export_postgres_backup
            status, archive = export_postgres_backup(url)
            if status != "ok":
                st.error(
                    "Yedek hazırlanamadı veya güvenli boyut limiti aşıldı."
                )
            else:
                filename = (
                    "AS_Control_Tower_ct_app_"
                    + datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
                    + ".zip"
                )
                st.download_button(
                    "Yedeği indir (özel şirket verisi içerir)",
                    data=archive, file_name=filename,
                    mime="application/zip", key="pg_backup_download",
                )
                st.caption(
                    "Yedek yalnızca oturum belleğinde oluşturuldu. "
                    "Dosyayı güvenli, şifrelenmiş depoda saklayın."
                )

    with roles:
        st.markdown(
            "**ADMIN:** Yönetim ve tüm iş modülleri.  "
            "**SALES:** CRM ve satış.  "
            "**PURCHASING:** Ürün, PO ve stok.  "
            "**QUALITY:** Kalite ve regülasyon.  "
            "**FINANCE:** Finans ve nakit.  "
            "**VIEWER:** Salt okunur yönetim."
        )
        st.caption(
            "Kullanıcı yetkileri Streamlit'in sunucu tarafındaki "
            "APP_USERS_JSON / CONTROL_TOWER_PASSWORD ayarından gelir."
        )
