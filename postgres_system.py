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
        if status == "company_scope_unsupported":
            st.error(
                "Dört şirketli şema algılandı. Eski 26-tablo ZIP dosyası "
                "şirket kayıtları ve izinleri dahil TAM yedek değildir. "
                "Bu indirme güvenlik için engellendi. Onaylı sağlayıcı "
                "tam yedeği ve bağımsız geri yükleme tatbikatı gerekir."
            )
            return
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




def render_postgres_quick_encrypted_backup(url):
    """ADMIN-only authenticated AES encrypted export and offline verification."""
    if current_role() != "ADMIN":
        return
    with st.expander("🔐 Şifreli PostgreSQL yedeği — hızlı erişim"):
        st.caption(
            "Free planında güvenli dış yedek için: En az 14 karakterli "
            "ayrı bir parola belirle. Dosya AES-256-GCM ile şifrelenir. "
            "Parola yedeğin içine yazılmaz; unutursan yedeği açamazsın."
        )
        pw = st.text_input(
            "Yedek parolası",
            type="password",
            key="ct_pg_encrypted_pw",
        )
        confirmation = st.text_input(
            "Yedek parolasını tekrar yaz",
            type="password",
            key="ct_pg_encrypted_pw_again",
        )
        saved = st.checkbox(
            "Parolamı yedekten ayrı, güvenli bir yerde saklayacağım.",
            key="ct_pg_encrypted_password_saved",
        )
        can_export = bool(
            saved and pw == confirmation and len(pw) >= 14
        )
        if st.button(
            "🔐 AES şifreli PostgreSQL yedeği hazırla",
            key="ct_pg_encrypted_prepare",
            disabled=not can_export,
        ):
            from scripts.postgres_backup import export_postgres_backup
            from scripts.postgres_encrypted_backup import encrypt_export_zip

            with st.spinner("Kalıcı veritabanının şifreli yedeği oluşturuluyor..."):
                status, archive = export_postgres_backup(url)
                if status == "ok":
                    enc_status, payload = encrypt_export_zip(archive, pw)
                else:
                    enc_status, payload = "export_failed", None
            if status == "company_scope_unsupported":
                st.error(
                    "Dört şirketli şema algılandı. Eski 26-tablo ZIP/AES "
                    "yedeği yeni şirket ve yetki tablolarını kapsamaz. "
                    "Eksik yedek oluşturulmadı; tam sağlayıcı yedeği ve "
                    "ayrı geri yükleme doğrulaması gerekir."
                )
            elif enc_status != "encrypted":
                st.error(
                    "Şifreli yedek hazırlanamadı. Veri değiştirilmedi. "
                    "Yedekleme sınırlarını ve parolanı kontrol et."
                )
            else:
                filename = (
                    "AS_Control_Tower_ct_app_encrypted_"
                    + datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
                    + ".asct"
                )
                st.success("AES-256 şifreli yedek hazır. Dosyayı güvenli yere indir.")
                st.download_button(
                    "🔐 Şifreli yedeği indir (.asct)",
                    data=payload, file_name=filename,
                    mime="application/octet-stream",
                    key="ct_pg_encrypted_download",
                )

        st.markdown("#### Şifreli yedeğin bütünlüğünü doğrula")
        st.caption(
            "İndirdiğin .asct dosyasını kendi Streamlit ekranında kontrol et. "
            "Parolan sohbet veya veritabanına gönderilmez."
        )
        uploaded = st.file_uploader(
            "Doğrulanacak şifreli yedek (.asct)",
            type=["asct"],
            key="ct_pg_encrypted_verify_file",
        )
        verify_pw = st.text_input(
            "Doğrulama parolası",
            type="password",
            key="ct_pg_encrypted_verify_pw",
        )
        if uploaded is not None and st.button(
            "🔎 Şifreli dosyayı doğrula",
            key="ct_pg_encrypted_verify_click",
            disabled=not bool(verify_pw),
        ):
            from scripts.postgres_encrypted_backup import inspect_encrypted_export

            with st.spinner("AES doğrulama etiketi ve ZIP tabloları inceleniyor..."):
                status, report = inspect_encrypted_export(
                    uploaded.getvalue(), verify_pw,
                )
            if status != "verified_encrypted":
                st.error(
                    "Şifreli dosya veya parola doğrulanamadı. "
                    "Bu yedeğe güvenerek geri yükleme yapma."
                )
            else:
                st.success(
                    f"AES ve ZIP iç bütünlüğü doğrulandı: "
                    f"{report['table_count']} tablo, "
                    f"{report['row_count']} kayıt. Bu bir geri yükleme testi değildir."
                )
                st.code(report["encrypted_sha256"], language="text")
                st.caption("SHA-256 şifreli dosyaya aittir. Parolanı koru.")



def render_postgres_quick_backup_verify():
    """Verify a user's existing ZIP in memory; never touch PostgreSQL."""
    if current_role() != "ADMIN":
        return
    with st.expander("🧪 İndirilen yedeği doğrula — hızlı erişim"):
        st.caption(
            "Telefonuna veya Mac'ine indirdiğin AS Control Tower ZIP dosyasını "
            "buradan seç. Dosya yalnızca uygulama sunucusunun belleğinde "
            "kontrol edilir; ChatGPT'ye gönderilmez veya veritabanına "
            "geri yüklenmez. İçerdiği müşteri/finans kayıtları gösterilmez."
        )
        uploaded = st.file_uploader(
            "Doğrulanacak ZIP dosyası",
            type=["zip"],
            key="ct_pg_verify_export_zip",
            help="Yalnızca AS Control Tower 26 tabloluk uygulama yedeği (en fazla 30 MB).",
        )
        if uploaded is None:
            st.info("İndirdiğin ZIP dosyasını seç; kayıtlar değiştirilmez.")
            return
        if st.button("ZIP bütünlüğünü doğrula", key="ct_pg_verify_export_button"):
            from scripts.postgres_backup_verify import inspect_export_zip

            with st.spinner("26 tablo, SHA-256 ve kayıt yapısı doğrulanıyor..."):
                status, report = inspect_export_zip(uploaded.getvalue())
            if status != "verified_format":
                st.error(
                    "Yedek formatı veya bütünlüğü doğrulanamadı. "
                    "Bu dosyaya güvenerek işlem yapma; yeniden yedek al. "
                    "Kontrol kodu: " + status
                )
                return
            st.success(
                f"ZIP iç bütünlüğü doğrulandı: {report['table_count']} tablo, "
                f"{report['row_count']} kayıt. Bu test geri yükleme değildir."
            )
            st.caption("Yedek oluşturulma zamanı (UTC): " + report["exported_utc"])
            st.code(report["sha256"], language="text")
            st.caption("SHA-256, dosyayı ileride yeniden karşılaştırabilmen içindir.")
            st.dataframe(
                pd.DataFrame([
                    {"Tablo": name, "Kayıt sayısı": count}
                    for name, count in report["table_counts"].items()
                ]),
                hide_index=True, width="stretch",
            )
            st.warning(
                "ZIP dosyası şifreli değildir. Güvenli bir klasörde sakla. "
                "Dosyanın gerçekten geri yüklenebilirliği ve Supabase "
                "otomatik yedekleme politikası bu doğrulama ile onaylanmaz."
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


def render_postgres_quick_acceptance(url):
    """Conservative operator launch status; never alters Supabase rows."""
    if current_role() != "ADMIN":
        return
    with st.expander("📋 Canlı kullanım kabul raporu — hızlı erişim"):
        st.caption(
            "Boş stok veya finans tablolarında sıfır tutarsızlık, "
            "o iş akışının gerçek ortamda sınandığı anlamına gelmez."
        )
        if st.button("Kabul durumunu salt okunur kontrol et", key="ct_pg_acceptance_run"):
            from scripts.postgres_acceptance import evaluate_acceptance

            with st.spinner("Canlı veri durumunu inceliyorum..."):
                report = evaluate_acceptance(url)
            if report["status"] == "failed":
                st.error("Kabul kontrolü başarısız; PostgreSQL şemasını kontrol edin.")
                return
            if report["critical"]:
                st.error(
                    f"{report['critical']} kritik veri tutarsızlığı bulundu; "
                    "iş kayıtlarına devam etmeden inceleyin."
                )
            else:
                st.info(
                    "Veri bütünlüğü kurallarında kritik hata bulunmadı; "
                    "ancak üretim kabulü ve finans doğrulaması tamamlanmadı."
                )
            st.dataframe(
                pd.DataFrame([
                    {
                        "Bölüm": area["area"],
                        "Kayıt": area["record_count"],
                        "Değerlendirme": area["status"],
                    }
                    for area in report["areas"]
                ]), width="stretch", hide_index=True,
            )
            for gate in report["external_gates"]:
                st.caption("• " + gate)


def render_postgres_master_import(url):
    """Preview-only until an ADMIN confirms a specific real-data CSV batch."""
    if current_role() != "ADMIN":
        return
    with st.expander("📥 Şirket verilerini içe aktar — hızlı erişim"):
        st.caption(
            "Müşteri, ürün ve depoları sadece CSV dosyasından, "
            "önizleme ve açık onayla ekler. Hiçbir demo veri yüklenmez. "
            "Var olan kayıtları güncellemez veya silmez."
        )
        from scripts.postgres_master_import import (
            APPROVAL, DOMAINS, import_new_masters,
            parse_master_csv, template_csv,
        )
        domain = st.selectbox(
            "Aktarılacak kayıt türü",
            tuple(DOMAINS),
            key="ct_pg_bulk_domain",
        )
        st.download_button(
            "📄 Boş CSV şablonunu indir",
            data=template_csv(domain),
            file_name={
                "Müşteriler": "as_control_tower_musteriler.csv",
                "Ürünler": "as_control_tower_urunler.csv",
                "Depolar": "as_control_tower_depolar.csv",
            }[domain],
            mime="text/csv",
            key="ct_pg_bulk_template",
        )
        uploaded = st.file_uploader(
            "Onaylı gerçek şirket kayıtlarının CSV dosyası",
            type=["csv"],
            key="ct_pg_bulk_file",
            help="UTF-8 biçimi; dosya başına en fazla 150 kayıt ve 512 KB.",
        )
        if uploaded is None:
            st.info("Önce boş şablonu doldurup dosyayı seçin. Henüz aktarım yapılmaz.")
            return
        status, rows = parse_master_csv(uploaded.getvalue(), domain)
        if status != "ok":
            st.error(
                "CSV biçimi, gerekli alanlar veya kayıt değerleri geçersiz. "
                "Lütfen indirilen şablonu kullanın. Hiçbir kayıt eklenmedi."
            )
            st.caption("Kontrol kodu: " + str(status))
            return
        st.success(
            f"{len(rows)} yeni kayıt önizlemede doğrulandı. "
            "Bu aşamada PostgreSQL'e hiçbir şey yazılmadı."
        )
        st.dataframe(
            pd.DataFrame(rows).head(20),
            width="stretch", hide_index=True,
        )
        if len(rows) > 20:
            st.caption(f"İlk 20 / {len(rows)} kayıt gösteriliyor.")

        backup_confirmed = st.checkbox(
            "Bu işlemden önce güncel PostgreSQL ZIP yedeğini "
            "indirdim ve güvenli şekilde sakladım.",
            key="ct_pg_bulk_backup_confirm",
        )
        confirmation = st.text_input(
            "Kalıcı, sadece yeni kayıt eklemeyi onaylamak için "
            f"{APPROVAL} yazın",
            key="ct_pg_bulk_phrase",
        )
        if st.button(
            f"{len(rows)} yeni kaydı PostgreSQL'e ekle",
            key="ct_pg_bulk_submit",
            disabled=not (backup_confirmed and confirmation == APPROVAL),
        ):
            # No user-supplied URLs/SQL: only the trusted Streamlit secret and
            # the authenticated session role are passed into the engine.
            actor = str((current_user() or {}).get("username", ""))
            result, inserted = import_new_masters(
                url,
                role=current_role(),
                actor=actor,
                domain=domain,
                rows=rows,
                confirmation=confirmation,
                backup_confirmed=backup_confirmed,
            )
            if result == "ok":
                st.success(
                    f"{inserted} kayıt kalıcı PostgreSQL ct_app veritabanına "
                    "eklendi; her işlem denetim günlüğüne yazıldı."
                )
            elif result == "duplicate_existing":
                st.warning(
                    "Dosyadaki en az bir ad sistemde zaten var. "
                    "Mükerrer kaydı çıkartıp yeniden deneyin. "
                    "Bu dosyadan hiçbir kayıt eklenmedi."
                )
            else:
                st.error(
                    "Aktarım güvenlik/doğrulama kontrolünde durduruldu; "
                    "bu dosyadan hiçbir kayıt eklenmedi. Kod: "
                    + str(result)
                )


def render_postgres_quick_security(url):
    """Read-only DB security posture; require ADMIN and an explicit click."""
    if current_role() != "ADMIN":
        return
    with st.expander("🔐 PostgreSQL güvenlik kontrolü — hızlı erişim"):
        st.caption(
            "TLS, veritabanı rolü, tablo RLS durumu ve temel erişim "
            "yetkileri yalnızca okunur. Supabase otomatik yedeklerinin "
            "durumu bu sorguyla doğrulanamaz."
        )
        if st.button(
            "Veritabanı güvenlik durumunu kontrol et",
            key="ct_pg_security_posture_run",
        ):
            from scripts.postgres_security_audit import audit_postgres_security

            with st.spinner("PostgreSQL izinleri salt okunur denetleniyor..."):
                result = audit_postgres_security(url)
            if result["status"] not in ("review_required",):
                st.error(
                    "Güvenlik durumu okunamadı. Hiçbir ayar veya kayıt değiştirilmedi."
                )
                return
            st.info(
                "Temel güvenlik ölçümleri kontrol edildi; "
                "üretim güvenliği ve Supabase yedekleme ayarları için "
                "yönetici incelemesi gereklidir."
            )
            st.dataframe(
                pd.DataFrame([
                    {
                        "Kontrol": check["label"],
                        "Durum": check["status"],
                        "Açıklama": check["detail"],
                    }
                    for check in result["checks"]
                ]), hide_index=True, width="stretch",
            )
            st.markdown("##### Supabase hesabından doğrulanması gerekenler")
            for requirement in result["external"]:
                st.caption("• " + requirement)


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
