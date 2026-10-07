import hashlib
import hmac
import json
import re
import sqlite3
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
        submit = st.form_submit_button("Giriş", type="primary", use_container_width=True)
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

    health_tab, audit_tab, backup_tab, users_tab = st.tabs(
        ["🩺 Sistem Sağlığı","🧾 Audit Log","💾 Yedekleme","👥 Rol Yapısı"]
    )

    with health_tab:
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
        st.dataframe(pd.DataFrame(rows),use_container_width=True,hide_index=True)
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
        st.dataframe(audit,use_container_width=True,hide_index=True)

    with backup_tab:
        db_file=Path(db_path)
        if db_file.exists():
            data=db_file.read_bytes()
            filename="as_control_tower_backup_" + date_stamp() + ".db"
            st.download_button(
                "Tam veritabanı yedeğini indir",
                data=data,
                file_name=filename,
                mime="application/octet-stream",
                use_container_width=True,
                type="primary",
            )
            st.warning(
                "Bu indirme manuel yedektir. Kalıcı otomatik bulut yedeği için "
                "yönetilen PostgreSQL/Supabase bağlantısı ayrıca yapılmalıdır."
            )

    with users_tab:
        users=load_users()
        safe=[{
            "Kullanıcı":u["username"],
            "Ad":u["display_name"],
            "Rol":u["role"],
            "Aktif":u["enabled"],
        } for u in users]
        st.dataframe(pd.DataFrame(safe),use_container_width=True,hide_index=True)
        st.code(
            '{"users":[{"username":"serkan","display_name":"Serkan","role":"ADMIN",'
            '"password_hash":"...","enabled":true}]}',
            language="json"
        )
        new_password=st.text_input("Yeni kullanıcı için şifre hash'i üret",type="password")
        if st.button("Hash üret",key="ct_hash_generate") and new_password:
            st.code(hash_password(new_password))
