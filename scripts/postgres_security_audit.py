"""Read-only operational security posture for the connected ct_app database.

This is not a Supabase Management API client. Provider-managed PITR, scheduled
backups, backup retention, network firewalls, password rotation and application
permission settings cannot be proved solely by SQL and remain explicitly
unverified. No secrets, private database-login names, usernames or company rows are
returned. Caller/UI must enforce an authenticated ADMIN session.
"""
from scripts.postgres_connection import sslmode_for
from scripts.staging_transaction_smoke import validate_test_url
from scripts.staging_validate import validate_staging_structure

# Manual provider checks are deliberately never reported as successful by SQL.
EXTERNAL_REQUIREMENTS = (
    "Supabase otomatik yedekleme ve saklama süresi: hesapta doğrulanmalı",
    "Yedekten geri yükleme ve olağanüstü durum tatbikatı: hesapta doğrulanmalı",
    "Streamlit Secrets erişimi ve şifre/anahtar rotasyonu: yönetici doğrulamalı",
    "Çok kullanıcılı yetki ve banka mutabakatı: canlı işlemlerle sınanmalı",
)


def audit_postgres_security(url):
    """Return sanitised posture summary. Never DDL, DML or secret disclosure.

    status = invalid_url | schema_mismatch | failed | review_required
    No 'production_ready' status is possible without independent verification.
    """
    if not validate_test_url(url):
        return {"status": "invalid_url", "checks": [], "external": EXTERNAL_REQUIREMENTS}
    try:
        schema_status, _ = validate_staging_structure(url, schema="ct_app")
        if schema_status != "ok":
            return {
                "status": "schema_mismatch",
                "checks": [],
                "external": EXTERNAL_REQUIREMENTS,
            }

        import psycopg
        with psycopg.connect(
            str(url).strip(), connect_timeout=8, sslmode=sslmode_for(url),
            autocommit=True,
        ) as conn:
            with conn.transaction():
                with conn.cursor() as cur:
                    cur.execute("SET TRANSACTION READ ONLY")
                    cur.execute("SET LOCAL statement_timeout = '15s'")
                    cur.execute("SET LOCAL lock_timeout = '3s'")
                    cur.execute(
                        "SELECT ssl FROM pg_stat_ssl WHERE pid=pg_backend_pid()"
                    )
                    ssl_row = cur.fetchone()
                    tls = bool(ssl_row and ssl_row[0])
                    cur.execute(
                        "SELECT rolsuper,rolbypassrls,rolcreaterole "
                        "FROM pg_roles WHERE rolname=current_user"
                    )
                    role = cur.fetchone()
                    if role is None:
                        raise ValueError("Role could not be verified")
                    elevated = any(bool(v) for v in role)
                    cur.execute(
                        "SELECT COUNT(*),COALESCE(SUM(CASE WHEN c.relrowsecurity "
                        "THEN 1 ELSE 0 END),0) "
                        "FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace "
                        "WHERE n.nspname='ct_app' AND c.relkind='r'"
                    )
                    total_tables, rls_tables = (int(v) for v in cur.fetchone())
                    cur.execute(
                        "SELECT "
                        "has_table_privilege(current_user,'ct_app.customers','SELECT'),"
                        "has_table_privilege(current_user,'ct_app.audit_log','INSERT')"
                    )
                    rights = cur.fetchone()
                    customer_read = bool(rights and rights[0])
                    audit_write = bool(rights and rights[1])

                    # Check ACTUAL current API-role permissions. RLS alone
                    # does not prove internet exposure when USAGE/GRANT is
                    # absent. Only fixed pg_catalog aggregates are returned.
                    cur.execute(
                        "SELECT "
                        "COUNT(*) FILTER (WHERE r.rolname='anon' "
                        "AND has_schema_privilege(r.oid,n.oid,'USAGE') "
                        "AND (has_table_privilege(r.oid,c.oid,'SELECT') "
                        "OR has_table_privilege(r.oid,c.oid,'INSERT') "
                        "OR has_table_privilege(r.oid,c.oid,'UPDATE') "
                        "OR has_table_privilege(r.oid,c.oid,'DELETE'))), "
                        "COUNT(*) FILTER (WHERE r.rolname='authenticated' "
                        "AND has_schema_privilege(r.oid,n.oid,'USAGE') "
                        "AND (has_table_privilege(r.oid,c.oid,'SELECT') "
                        "OR has_table_privilege(r.oid,c.oid,'INSERT') "
                        "OR has_table_privilege(r.oid,c.oid,'UPDATE') "
                        "OR has_table_privilege(r.oid,c.oid,'DELETE'))) "
                        "FROM pg_roles r "
                        "JOIN pg_namespace n ON n.nspname='ct_app' "
                        "JOIN pg_class c ON c.relnamespace=n.oid "
                        "AND c.relkind='r' "
                        "WHERE r.rolname IN ('anon','authenticated')"
                    )
                    grants = cur.fetchone()
                    if grants is None:
                        raise ValueError("Could not assess API-role privileges")
                    anon_access, authenticated_access = (int(v) for v in grants)

        checks = [
            {
                "label": "PostgreSQL TLS bağlantısı",
                "status": "uygun" if tls else "uyarı",
                "detail": (
                    "Bağlantı şifrelenmiş görünüyor; sertifika/hostname "
                    "doğrulaması ayrıca incelenmeli."
                    if tls else
                    "Bu bağlantı şifreli görünmüyor; üretim için uygun değil."
                ),
            },
            {
                "label": "Uygulama veritabanı rolünün ayrıcalıkları",
                "status": "incele" if elevated else "uygun",
                "detail": (
                    "Veritabanı bağlantısında yönetici/RLS atlama yetkisi "
                    "olabilir. En az yetkili ayrı bir rol değerlendirilmeli."
                    if elevated else
                    "Bağlantı rolünde süper kullanıcı veya RLS atlama "
                    "yetkisi görünmüyor."
                ),
            },
            {
                "label": "ct_app tablo satır güvenliği (RLS)",
                "status": "incele" if rls_tables < total_tables else "uygun",
                "detail": (
                    f"{rls_tables}/{total_tables} tabloda RLS etkin. "
                    "Streamlit yalnızca sunucu bağlantısı kullanıyorsa "
                    "RLS isteğe bağlı olabilir; doğrudan istemci erişimi varsa "
                    "güvenlik politikası mutlaka değerlendirilmelidir."
                ),
            },
            {
                "label": "Supabase API rolleri için fiili ct_app erişimi",
                "status": (
                    "uyarı" if (anon_access or authenticated_access)
                    and rls_tables < total_tables else
                    "incele" if (anon_access or authenticated_access)
                    else "uygun"
                ),
                "detail": (
                    f"Anonim rolün {anon_access}, oturum açmış API rolünün "
                    f"{authenticated_access} tabloya şema ve tablo izinleriyle "
                    "erişim hakkı var. RLS politika ve açık API yüzeyi "
                    "ayrıca incelenmeli."
                    if anon_access or authenticated_access else
                    "Şu anda anon veya authenticated API rolleri için ct_app "
                    "tablolarında doğrudan erişim izni bulunmadı. RLS yine de "
                    "savunma amaçlı değerlendirilmeli; gelecekte izinler "
                    "değişirse bu sonuç da değişebilir."
                ),
            },
            {
                "label": "CRM okuma ve denetim günlüğü yetkileri",
                "status": "uygun" if customer_read and audit_write else "uyarı",
                "detail": (
                    "Müşteri okuma ve işlem günlüğü ekleme yetkileri mevcut."
                    if customer_read and audit_write else
                    "Müşteri okuma veya audit-log ekleme yetkisi eksik."
                ),
            },
        ]
        return {
            "status": "review_required",
            "checks": checks,
            "external": EXTERNAL_REQUIREMENTS,
        }
    except Exception:
        return {
            "status": "failed",
            "checks": [],
            "external": EXTERNAL_REQUIREMENTS,
        }
