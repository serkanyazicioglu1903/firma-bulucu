import hashlib
import hmac
import io
import json
import re
import sqlite3
import zipfile
import tempfile
from urllib.parse import quote
from datetime import datetime
from pathlib import Path

import pandas as pd
import streamlit as st


ROLE_PERMISSIONS = {
    "ADMIN": {"*"},
    "SALES": {"dashboard","crm","intelligence","pricing","pipeline","followup","tasks","ai"},
    "PURCHASING": {"dashboard","products","procurement","stock","tasks","quality","ai"},
    "FINANCE": {"dashboard","pricing","finance","tasks","ai","reports"},
    "QUALITY": {"dashboard","quality","regulatory","tasks","crm","ai"},
    "VIEWER": {"dashboard","reports","ai","ceo"},
}


def connect(db_path):
    conn = sqlite3.connect(Path(db_path), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


def init_security_tables(db_path):
    with connect(db_path) as conn:
        conn.executescript("""
        CREATE TABLE IF NOT EXISTS audit_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            username TEXT DEFAULT '',
            display_name TEXT DEFAULT '',
            role TEXT DEFAULT '',
            action TEXT NOT NULL,
            table_name TEXT DEFAULT '',
            sql_preview TEXT DEFAULT '',
            session_id TEXT DEFAULT ''
        );

        CREATE TABLE IF NOT EXISTS system_settings (
            setting_key TEXT PRIMARY KEY,
            setting_value TEXT DEFAULT '',
            updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
            updated_by TEXT DEFAULT ''
        );
        """)
        conn.commit()


def _secret(name, default=""):
    try:
        return st.secrets.get(name, default)
    except Exception:
        return default


def hash_password(password, salt=None):
    if salt is None:
        salt = hashlib.sha256(str(datetime.utcnow().timestamp()).encode()).hexdigest()[:32]
    digest = hashlib.pbkdf2_hmac(
        "sha256", str(password).encode("utf-8"), str(salt).encode("utf-8"), 200_000
    ).hex()
    return "pbkdf2_sha256$200000$" + str(salt) + "$" + digest


def verify_password(password, stored):
    stored = str(stored or "")
    if stored.startswith("pbkdf2_sha256$"):
        try:
            _, rounds, salt, expected = stored.split("$", 3)
            digest = hashlib.pbkdf2_hmac(
                "sha256", str(password).encode("utf-8"), salt.encode("utf-8"), int(rounds)
            ).hex()
            return hmac.compare_digest(digest, expected)
        except Exception:
            return False
    return hmac.compare_digest(str(password), stored)


def load_users():
    raw = _secret("APP_USERS_JSON", "")
    users = []
    if raw:
        try:
            parsed = json.loads(str(raw))
            if isinstance(parsed, dict):
                parsed = parsed.get("users", [])
            if isinstance(parsed, list):
                users = parsed
        except Exception:
            users = []

    if users:
        clean = []
        for item in users:
            if not isinstance(item, dict):
                continue
            username = str(item.get("username","")).strip().lower()
            if not username:
                continue
            clean.append({
                "username": username,
                "display_name": str(item.get("display_name") or username),
                "role": str(item.get("role") or "VIEWER").upper(),
                "password": str(item.get("password") or ""),
                "password_hash": str(item.get("password_hash") or ""),
                "enabled": bool(item.get("enabled", True)),
            })
        return clean

    admin_password = str(_secret("CONTROL_TOWER_PASSWORD", "") or "")
    if admin_password:
        return [{
            "username": "serkan",
            "display_name": "Serkan",
            "role": "ADMIN",
            "password": admin_password,
            "password_hash": "",
            "enabled": True,
        }]
    return []


def authenticate(username, password):
    username = str(username or "").strip().lower()
    for user in load_users():
        if user["username"] != username or not user["enabled"]:
            continue
        stored = user["password_hash"] or user["password"]
        if verify_password(password, stored):
            return user
    return None


def current_user():
    return st.session_state.get("ct_user")


def current_role():
    user = current_user() or {}
    return str(user.get("role") or "").upper()


def can_access(module):
    role = current_role()
    perms = ROLE_PERMISSIONS.get(role, set())
    return "*" in perms or module in perms


def access_denied(module):
    st.warning("Bu bölüm için yetkin yok. Rol: " + (current_role() or "-"))


def login_gate():
    users = load_users()
    if not users:
        st.error(
            "AS Control Tower güvenlik kurulumu tamamlanmamış. "
            "Streamlit Secrets içine CONTROL_TOWER_PASSWORD veya APP_USERS_JSON eklenmeden "
            "gerçek şirket verisi girilmemeli."
        )
        return False

    if current_user():
        return True

    st.markdown("### 🔐 AS Control Tower Giriş")
    st.caption("Şirket verilerine erişmek için kullanıcı hesabınla giriş yap.")
    with st.form("ct_login_form"):
        username = st.text_input("Kullanıcı adı", value="serkan")
        password = st.text_input("Şifre", type="password")
        submit = st.form_submit_button("Giriş", type="primary", width="stretch")
        if submit:
            user = authenticate(username, password)
            if user:
                st.session_state["ct_user"] = {
                    "username": user["username"],
                    "display_name": user["display_name"],
                    "role": user["role"],
                }
                st.session_state["ct_session_id"] = hashlib.sha256(
                    (user["username"] + "|" + datetime.utcnow().isoformat()).encode()
                ).hexdigest()[:20]
                st.rerun()
            st.error("Kullanıcı adı veya şifre yanlış.")
    return False


def logout_button():
    user = current_user()
    if not user:
        return
    c1,c2 = st.columns([4,1])
    c1.caption("👤 " + str(user.get("display_name","")) + " · " + str(user.get("role","")))
    if c2.button("Çıkış", key="ct_logout"):
        for key in ["ct_user","ct_session_id"]:
            st.session_state.pop(key, None)
        st.rerun()


WRITE_TABLE_PERMISSIONS = {
    "SALES": {
        "customers","contacts","opportunities","activities","tasks","quotes",
        "customer_product_status","opportunity_stage_history"
    },
    "PURCHASING": {
        "product_catalog","purchase_orders","shipments","inventory_lots",
        "inventory_policy","warehouses","tasks","customer_product_status"
    },
    "FINANCE": {
        "quotes","receivables","payables","finance_transactions",
        "cash_accounts","cash_events","tasks"
    },
    "QUALITY": {
        "quality_cases","quality_actions","quality_recoveries",
        "compliance_documents","regulatory_items","inventory_lots","tasks","activities"
    },
    "VIEWER": set(),
}


def sql_write_table(sql):
    sql_text=" ".join(str(sql or "").strip().split())
    patterns=[
        r"INSERT\s+INTO\s+([A-Za-z0-9_]+)",
        r"UPDATE\s+([A-Za-z0-9_]+)",
        r"DELETE\s+FROM\s+([A-Za-z0-9_]+)",
        r"REPLACE\s+INTO\s+([A-Za-z0-9_]+)",
    ]
    for pattern in patterns:
        m=re.search(pattern,sql_text,re.I)
        if m:
            return m.group(1)
    return ""


def authorize_write(sql):
    role=current_role()
    if role in ("","SYSTEM"):
        return True
    if role=="ADMIN":
        return True
    table=sql_write_table(sql)
    if not table:
        return True
    return table in WRITE_TABLE_PERMISSIONS.get(role,set())


def audit_sql_write(db_path, sql):
    sql_text = " ".join(str(sql or "").strip().split())
    if not sql_text:
        return
    verb = sql_text.split(" ",1)[0].upper()
    if verb not in {"INSERT","UPDATE","DELETE","REPLACE"}:
        return
    if re.search(r"\baudit_log\b", sql_text, re.I):
        return

    table = ""
    patterns = [
        r"INSERT\s+INTO\s+([A-Za-z0-9_]+)",
        r"UPDATE\s+([A-Za-z0-9_]+)",
        r"DELETE\s+FROM\s+([A-Za-z0-9_]+)",
        r"REPLACE\s+INTO\s+([A-Za-z0-9_]+)",
    ]
    for pattern in patterns:
        m = re.search(pattern, sql_text, re.I)
        if m:
            table = m.group(1)
            break

    user = current_user() or {}
    try:
        with connect(db_path) as conn:
            conn.execute(
                """INSERT INTO audit_log
                (username,display_name,role,action,table_name,sql_preview,session_id)
                VALUES (?,?,?,?,?,?,?)""",
                (
                    str(user.get("username") or "system"),
                    str(user.get("display_name") or "System"),
                    str(user.get("role") or "SYSTEM"),
                    verb,
                    table,
                    sql_text[:900],
                    str(st.session_state.get("ct_session_id","")),
                )
            )
            conn.commit()
    except Exception:
        pass


def query_df(db_path, sql, params=()):
    with connect(db_path) as conn:
        return pd.read_sql_query(sql, conn, params=params)


def date_stamp():
    return datetime.now().strftime("%Y%m%d_%H%M%S")


def verified_sqlite_backup_bytes(db_path):
    """Consistent SQLite backup verified before offering it for download.

    Never read a live SQLite file directly: WAL/uncommitted state can make
    a raw file copy incomplete. SQLite's online backup API creates a
    transactionally consistent snapshot instead.
    """
    source = Path(db_path).resolve()
    if not source.is_file():
        raise FileNotFoundError("SQLite veritabanı dosyası bulunamadı.")
    with tempfile.TemporaryDirectory(prefix="ct-sqlite-backup-") as folder:
        backup_file = Path(folder) / "as_control_tower_snapshot.db"
        source_uri = "file:" + quote(str(source), safe="/") + "?mode=ro"
        with sqlite3.connect(source_uri, uri=True) as original:
            with sqlite3.connect(backup_file) as snapshot:
                original.backup(snapshot)
        with sqlite3.connect(backup_file) as check:
            if check.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                raise RuntimeError("SQLite yedeğinin bütünlük kontrolü başarısız.")
        return backup_file.read_bytes()


def export_all_tables_zip(db_path):
    buffer=io.BytesIO()
    with connect(db_path) as conn, zipfile.ZipFile(buffer,"w",zipfile.ZIP_DEFLATED) as z:
        tables=[
            row[0] for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
            ).fetchall()
            if not row[0].startswith("sqlite_")
        ]
        for table in tables:
            df=pd.read_sql_query('SELECT * FROM "' + table + '"',conn)
            z.writestr(table + ".csv",df.to_csv(index=False))
    return buffer.getvalue()


def import_master_csv(db_path, table, uploaded_file):
    df=pd.read_csv(uploaded_file)
    if df.empty:
        return 0

    allowed={
        "customers":{
            "name","country","sector","status","owner","annual_potential","currency",
            "contact_name","contact_email","phone","source","notes"
        },
        "product_catalog":{
            "name","category","supplier","supplier_country","target_sectors",
            "applications","default_currency","default_opportunity_value","active","notes"
        },
        "tasks":{
            "title","related_to","owner","priority","due_date","status","notes"
        },
    }
    if table not in allowed:
        raise ValueError("Bu tablo toplu içe aktarma için açık değil.")

    cols=[c for c in df.columns if c in allowed[table]]
    if not cols:
        raise ValueError("Uygun sütun bulunamadı.")

    required={"customers":"name","product_catalog":"name","tasks":"title"}[table]
    if required not in cols:
        raise ValueError("Zorunlu sütun eksik: " + required)

    added=0
    with connect(db_path) as conn:
        for _,row in df.iterrows():
            values=[]
            use_cols=[]
            for col in cols:
                value=row[col]
                if pd.isna(value):
                    value=None
                values.append(value)
                use_cols.append(col)
            placeholders=",".join(["?"]*len(use_cols))
            columns=",".join(use_cols)
            if table in ("customers","product_catalog"):
                key_value=str(row[required]).strip()
                exists=conn.execute(
                    "SELECT COUNT(*) FROM " + table + " WHERE lower(" + required + ")=lower(?)",
                    (key_value,)
                ).fetchone()[0]
                if exists:
                    continue
            conn.execute(
                "INSERT INTO " + table + " (" + columns + ") VALUES (" + placeholders + ")",
                values
            )
            added+=1
        conn.commit()
    return added


def test_postgres_connection(url):
    """Check reachability without schema changes or leaking credentials."""
    from urllib.parse import urlsplit

    if not url or not str(url).strip():
        return False, "missing"
    url = str(url).strip()
    if "[YOUR-PASSWORD]" in url or "SUPABASE_BAGLANTI_ADRESIN" in url:
        return False, "placeholder"
    try:
        parsed = urlsplit(url)
        if parsed.scheme not in ("postgresql", "postgres") or not parsed.hostname:
            return False, "invalid_url"
        import psycopg
        with psycopg.connect(url, connect_timeout=8, sslmode="require") as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT 1")
                if cur.fetchone()[0] != 1:
                    return False, "unexpected_result"
        return True, "ok"
    except Exception:
        # Do not display raw DB exceptions: they can contain host/user/URL.
        return False, "connection_failed"


def inspect_postgres_staging(url, schema="ct_staging"):
    """Read-only metadata inspection. Returns no credentials or business rows."""
    if not url or not str(url).strip():
        return False, "missing", []
    if schema != "ct_staging":
        return False, "invalid_schema", []
    from urllib.parse import urlsplit
    try:
        parsed = urlsplit(str(url).strip())
        if parsed.scheme not in ("postgresql", "postgres") or not parsed.hostname:
            return False, "invalid_url", []
        import psycopg
        with psycopg.connect(str(url).strip(), connect_timeout=8, sslmode="require") as conn:
            with conn.cursor() as cur:
                cur.execute("SET TRANSACTION READ ONLY")
                cur.execute(
                    "SELECT table_name FROM information_schema.tables "
                    "WHERE table_schema = %s AND table_type = 'BASE TABLE' "
                    "ORDER BY table_name",
                    (schema,),
                )
                return True, "ok", [row[0] for row in cur.fetchall()]
    except Exception:
        # Never expose connection strings or PostgreSQL error messages in UI.
        return False, "connection_failed", []


def render_system_admin(db_path):
    init_security_tables(db_path)
    st.markdown("### ⚙️ Sistem Yönetimi")
    user = current_user() or {}
    st.caption(
        "Aktif kullanıcı: " + str(user.get("display_name","-")) +
        " · Rol: " + str(user.get("role","-"))
    )

    if current_role() != "ADMIN":
        access_denied("system")
        return

    health_tab, audit_tab, backup_tab, import_tab, users_tab = st.tabs(
        ["🩺 Sistem Sağlığı","🧾 Audit Log","💾 Yedekleme","📥 Toplu Veri","👥 Rol Yapısı"]
    )

    with health_tab:
        st.markdown("#### Supabase PostgreSQL bağlantısı")
        st.caption(
            "Bu kontrol yalnız SELECT 1 çalıştırır; tablo oluşturmaz, "
            "veri taşımaz ve bağlantı şifresini göstermez."
        )
        st.info(
            "Uygulamanın mevcut iş veritabanı hâlâ SQLite. "
            "Bağlantı testi başarılı olsa bile PostgreSQL'e geçiş yapılmış olmaz."
        )
        db_url = _secret("DATABASE_URL")
        if not db_url:
            st.warning("DATABASE_URL Streamlit Secrets içinde bulunamadı.")
        if st.button("Supabase bağlantısını test et", key="ct_postgres_test"):
            success, reason = test_postgres_connection(db_url)
            if success:
                st.success("Supabase PostgreSQL bağlantısı başarılı (salt okunur test).")
            elif reason == "missing":
                st.error("DATABASE_URL bulunamadı. Streamlit Secrets kaydını kontrol edin.")
            elif reason == "placeholder":
                st.error("Bağlantı adresinde [YOUR-PASSWORD] veya örnek metin kalmış.")
            elif reason == "invalid_url":
                st.error("DATABASE_URL geçerli bir PostgreSQL URI değil.")
            else:
                st.error(
                    "Supabase bağlantısı kurulamadı. Session pooler URI, "
                    "veritabanı şifresi, özel karakterlerin URL kodlaması "
                    "ve projenin aktif olduğunu kontrol edin."
                )

        st.markdown("#### PostgreSQL test tabloları (yalnızca kontrol)")
        st.caption(
            "Bu bölüm mevcut Supabase tablolarını sadece okur. "
            "SQLite kayıtlarını taşımaz, PostgreSQL tablolarını oluşturmaz."
        )
        if st.button("Supabase test tablolarını kontrol et", key="ct_pg_staging_inspect"):
            ok, reason, existing = inspect_postgres_staging(db_url)
            if ok:
                from scripts.build_pg_schema import generate
                _, expected = generate()
                missing = sorted(set(expected) - set(existing))
                st.info(
                    f"ct_staging: {len(existing)} mevcut tablo; "
                    f"{len(expected)} beklenen uygulama tablosu."
                )
                if missing:
                    st.warning(
                        "Henüz oluşturulmamış tablolar: " + ", ".join(missing)
                    )
                else:
                    st.success(
                        "Uygulamanın beklediği tablo adları test şemasında mevcut. "
                        "Bu kontrol kolonları, ilişkileri veya uygulama işlevlerini "
                        "henüz doğrulamaz."
                    )
            else:
                st.error(
                    "Salt okunur tablo kontrolü tamamlanamadı. "
                    "DATABASE_URL bağlantısını kontrol edin."
                )
        st.markdown("#### PostgreSQL tablo yapısı doğrulaması")
        st.caption(
            "26 uygulama tablosunun sütun adlarını, veri tiplerini, zorunlu alanlarını, "
            "birincil anahtarlarını, benzersizlik ve yabancı anahtar ilişkilerini "
            "salt okunur şekilde kontrol eder. Veri kayıtlarını okumaz veya değiştirmez."
        )
        if st.button("Tablo yapısı ve ilişkileri doğrula", key="ct_pg_schema_validate"):
            from scripts.staging_validate import validate_staging_structure
            status, issues = validate_staging_structure(db_url)
            if status == "ok":
                st.success(
                    "26 uygulama tablosunun sütun tipleri, zorunlu alanları ve "
                    "PK/UNIQUE/FK ilişkileri beklenen şemayla uyumlu. "
                    "Bu kontrol gerçek kayıt işlemlerini veya iş kurallarını sınamaz."
                )
            elif status == "mismatch":
                st.error(
                    f"PostgreSQL test şemasında {len(issues)} yapısal uyumsuzluk bulundu. "
                    "SQLite verilerini taşıma veya canlı sistemi değiştirme."
                )
                for issue in issues[:20]:
                    st.write("• " + issue)
                if len(issues) > 20:
                    st.caption(f"Diğer {len(issues)-20} uyumsuzluk gösterilmedi.")
            else:
                st.error(
                    "Salt okunur şema doğrulaması tamamlanamadı. "
                    "Bağlantı ve Supabase yetkilerini kontrol edin."
                )

        with st.expander("PostgreSQL işlem testleri (geri alınır)"):
            st.warning(
                "Bu test yalnızca ct_staging üzerinde geçici ve tamamen kurgusal "
                "müşteri, ürün, teklif, görev, sevkiyat, stok, kalite ve finans "
                "kayıtlarıyla çalışır. Test sonunda bütün ekleme/güncelleme/silme "
                "işlemleri geri alınır. Gerçek şirket verilerine dokunmaz; canlı "
                "SQLite uygulamasını PostgreSQL'e geçirmez."
            )
            test_confirm = st.checkbox(
                "Yalnızca ct_staging test ortamında geri alınacak deneme işlemlerini onaylıyorum.",
                key="ct_pg_transaction_smoke_confirm",
            )
            if st.button(
                "PostgreSQL işlem testini çalıştır",
                key="ct_pg_transaction_smoke_run",
                disabled=not test_confirm or not db_url,
            ):
                from scripts.staging_transaction_smoke import (
                    run_transactional_staging_smoke,
                )
                smoke_status, tested = run_transactional_staging_smoke(db_url)
                if smoke_status == "passed":
                    st.success(
                        "PostgreSQL geçici ekleme, okuma, güncelleme ve silme "
                        "işlemleri başarılı. Tüm deneme kayıtları geri alındı. "
                        "Kontrol edilen bağlantılar: " + ", ".join(tested) + ". "
                        "Canlı uygulama hâlâ SQLite kullanıyor."
                    )
                elif smoke_status == "schema_mismatch":
                    st.error(
                        "Test başlamadı: PostgreSQL tablo yapısı doğrulanamadı. "
                        "Önce salt okunur tablo yapısı testini çalıştır."
                    )
                else:
                    st.error(
                        "İşlem testi tamamlanamadı. Deneme değişiklikleri geri "
                        "alınır; hiçbir gerçek kayıt taşınmadı. "
                        "Supabase yetkilerini ve veritabanı bağlantısını kontrol et."
                    )

        with st.expander("Supabase test tablolarını güvenli oluştur"):
            st.warning(
                "Yalnızca ct_staging test şemasında boş uygulama tabloları oluşturur. "
                "Mevcut uygulama tabloları varsa işlemi durdurur. "
                "SQLite verilerini taşımaz ve canlı uygulamayı PostgreSQL'e geçirmez."
            )
            confirm = st.checkbox(
                "Yalnızca ct_staging test şemasında boş tablolar oluşturulmasını onaylıyorum.",
                key="ct_pg_bootstrap_confirm",
            )
            if st.button(
                "26 test tablosunu oluştur",
                key="ct_pg_bootstrap_apply",
                disabled=not confirm or not db_url,
            ):
                from scripts.staging_bootstrap import bootstrap_staging
                status, created = bootstrap_staging(db_url)
                if status == "created":
                    st.success(
                        f"{created} boş uygulama tablosu ct_staging içinde oluşturuldu. "
                        "Gerçek veri aktarılmadı; uygulama hâlâ SQLite kullanıyor."
                    )
                elif status == "already_present":
                    st.info("Beklenen tablolar zaten mevcut; hiçbir tablo değiştirilmedi.")
                elif status == "conflict":
                    st.error(
                        "ct_staging içinde beklenmeyen veya kısmen kurulmuş tablolar var. "
                        "Güvenlik nedeniyle hiçbir değişiklik yapılmadı."
                    )
                elif status == "schema_missing":
                    st.error(
                        "ct_staging şeması bulunamadı. "
                        "Önce test şemasının varlığı doğrulanmalı."
                    )
                else:
                    st.error(
                        "Test tabloları oluşturulamadı; işlem geri alındı. "
                        "Bağlantı, yetki ve test şeması durumunu kontrol edin."
                    )

        with st.expander("PostgreSQL test şeması SQL dosyası"):
            st.caption(
                "Yalnızca test şeması için çevrimdışı SQL üretir. "
                "Dosyayı indirmek veritabanını değiştirmez; "
                "SQL'i uygulamadan önce teknik inceleme gerekir."
            )
            try:
                from scripts.build_pg_schema import generate
                staging_sql, staging_tables = generate()
                st.download_button(
                    f"{len(staging_tables)} test tablosu SQL dosyasını indir",
                    data=staging_sql.encode("utf-8"),
                    file_name="as_control_tower_ct_staging_schema.sql",
                    mime="application/sql",
                    key="ct_download_pg_staging_sql",
                )
            except (ValueError, OSError, sqlite3.Error):
                st.error("Test şeması SQL dosyası hazırlanamadı.")

        tables = [
            "customers","opportunities","tasks","product_catalog","quotes",
            "purchase_orders","shipments","inventory_lots","receivables",
            "payables","quality_cases","compliance_documents","audit_log"
        ]
        rows=[]
        with connect(db_path) as conn:
            for table in tables:
                try:
                    count=conn.execute("SELECT COUNT(*) FROM " + table).fetchone()[0]
                    rows.append({"Tablo":table,"Kayıt":int(count),"Durum":"OK"})
                except Exception as exc:
                    rows.append({"Tablo":table,"Kayıt":0,"Durum":"HATA: " + str(exc)})
        st.dataframe(pd.DataFrame(rows),width="stretch",hide_index=True)
        db_file=Path(db_path)
        if db_file.exists():
            st.metric("Veritabanı boyutu",f"{db_file.stat().st_size/1024/1024:.2f} MB")

    with audit_tab:
        audit=query_df(db_path, """
            SELECT created_at AS tarih,display_name AS kullanıcı,role AS rol,
                   action AS işlem,table_name AS tablo,sql_preview AS kayıt
            FROM audit_log
            ORDER BY id DESC LIMIT 500
        """)
        st.dataframe(audit,width="stretch",hide_index=True)

    with backup_tab:
        db_file = Path(db_path)
        if db_file.exists():
            st.caption(
                "Güvenli bir SQLite anlık görüntüsü ve ona ait SHA256 doğrulama "
                "raporunu aynı oturumda hazırla. İki dosyayı birlikte sakla."
            )
            if st.button("Güvenli yedeği hazırla", key="ct_prepare_sqlite_backup"):
                try:
                    from scripts.backup_report import build_backup_manifest
                    data = verified_sqlite_backup_bytes(db_path)
                    filename = "as_control_tower_backup_" + date_stamp() + ".db"
                    report = build_backup_manifest(data, filename)
                    st.session_state["ct_backup_bytes"] = data
                    st.session_state["ct_backup_filename"] = filename
                    st.session_state["ct_backup_manifest"] = report
                except (OSError, sqlite3.Error, RuntimeError, ValueError):
                    for key in ("ct_backup_bytes", "ct_backup_filename", "ct_backup_manifest"):
                        st.session_state.pop(key, None)
                    st.error("Yedek doğrulanamadı. Mevcut veritabanı değiştirilmedi.")

            data = st.session_state.get("ct_backup_bytes")
            manifest = st.session_state.get("ct_backup_manifest")
            if data and manifest:
                st.success(
                    "SQLite bütünlük kontrolü başarılı: "
                    + str(manifest["byte_size"]) + " bayt, "
                    + str(len(manifest["table_counts"])) + " tablo, "
                    + str(sum(manifest["table_counts"].values())) + " kayıt."
                )
                st.caption("SHA256: " + manifest["sha256"])
                if manifest["foreign_key_check"] != "ok":
                    st.warning(
                        "Yedekte ilişki tutarsızlıkları bulundu. Yedek saklanabilir; "
                        "ancak PostgreSQL aktarımı yapılmamalıdır."
                    )
                st.download_button(
                    "Tam veritabanı yedeğini indir",
                    data=data,
                    file_name=manifest["backup_filename"],
                    mime="application/octet-stream",
                    width="stretch",
                    type="primary",
                    key="ct_download_sqlite_backup",
                )
                st.download_button(
                    "Yedek doğrulama raporunu indir (JSON)",
                    data=json.dumps(
                        manifest, ensure_ascii=False, indent=2, sort_keys=True
                    ).encode("utf-8"),
                    file_name=manifest["backup_filename"] + ".json",
                    mime="application/json",
                    width="stretch",
                    key="ct_download_sqlite_manifest",
                )
                with st.expander("Yedekteki tablo ve kayıt sayıları (yalnızca özet)"):
                    st.dataframe(
                        pd.DataFrame(
                            [{"Tablo": name, "Kayıt": count}
                             for name, count in sorted(manifest["table_counts"].items())]
                        ), width="stretch", hide_index=True
                    )
                st.caption(
                    "Bu rapor sadece bu oturumda hazırlanan yeni yedeğe aittir; "
                    "daha önce indirilen farklı bir dosyayı doğruladığı anlamına gelmez. "
                    "Her iki dosyayı iCloud Drive'da özel klasöre kaydet. "
                    "Veritabanı dosyasını GitHub'a veya sohbete yükleme."
                )
            st.download_button(
                "Tüm tabloları CSV ZIP olarak indir",
                data=export_all_tables_zip(db_path),
                file_name="as_control_tower_csv_" + date_stamp() + ".zip",
                mime="application/zip",
                width="stretch",
            )
            st.warning(
                "Bu indirme manuel yedektir. Kalıcı otomatik bulut yedeği için "
                "yönetilen PostgreSQL/Supabase bağlantısı ayrıca yapılmalıdır."
            )

    with import_tab:
        table=st.selectbox(
            "İçe aktarım türü",
            ["customers","product_catalog","tasks"],
            format_func=lambda x:{
                "customers":"Müşteriler",
                "product_catalog":"Ürün Kataloğu",
                "tasks":"Görevler"
            }[x]
        )
        st.caption(
            "Müşteriler: name zorunlu · Ürünler: name zorunlu · Görevler: title zorunlu."
        )
        upload=st.file_uploader("CSV dosyası",type=["csv"],key="system_bulk_import")
        if upload is not None:
            try:
                preview=pd.read_csv(upload)
                st.dataframe(preview.head(20),width="stretch",hide_index=True)
                upload.seek(0)
                if st.button("CSV'yi içe aktar",type="primary",key="system_import_button"):
                    n=import_master_csv(db_path,table,upload)
                    st.success(str(n) + " yeni kayıt içe aktarıldı.")
                    st.rerun()
            except Exception as exc:
                st.error("CSV okunamadı: " + str(exc))

    with users_tab:
        users=load_users()
        safe=[{
            "Kullanıcı":u["username"],
            "Ad":u["display_name"],
            "Rol":u["role"],
            "Aktif":u["enabled"],
        } for u in users]
        st.dataframe(pd.DataFrame(safe),width="stretch",hide_index=True)
        st.code(
            '{"users":[{"username":"serkan","display_name":"Serkan","role":"ADMIN",'
            '"password_hash":"...","enabled":true}]}',
            language="json"
        )
        new_password=st.text_input("Yeni kullanıcı için şifre hash'i üret",type="password")
        if st.button("Hash üret",key="ct_hash_generate") and new_password:
            st.code(hash_password(new_password))
