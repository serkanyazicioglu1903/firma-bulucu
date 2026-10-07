import sqlite3
from datetime import date, datetime, timedelta
from pathlib import Path

import pandas as pd
import streamlit as st

from microsoft_graph import (
    attendee_addresses,
    finish_device_flow,
    get_cached_token,
    get_calendar_events,
    get_profile,
    get_recent_messages,
    primary_sender,
    start_device_flow,
)

GENERIC_EMAIL_DOMAINS = {
    "gmail.com","hotmail.com","outlook.com","yahoo.com","icloud.com",
    "aol.com","live.com","msn.com","proton.me","protonmail.com"
}


def connect(db_path):
    conn = sqlite3.connect(Path(db_path), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


def execute(db_path, sql, params=()):
    with connect(db_path) as conn:
        conn.execute(sql, params)
        conn.commit()


def query_df(db_path, sql, params=()):
    with connect(db_path) as conn:
        return pd.read_sql_query(sql, conn, params=params)


def init_outlook_tables(db_path):
    with connect(db_path) as conn:
        conn.executescript("""
        CREATE TABLE IF NOT EXISTS outlook_messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            outlook_id TEXT NOT NULL UNIQUE,
            conversation_id TEXT DEFAULT '',
            subject TEXT DEFAULT '',
            sender_name TEXT DEFAULT '',
            sender_email TEXT DEFAULT '',
            received_at TEXT DEFAULT '',
            body_preview TEXT DEFAULT '',
            web_link TEXT DEFAULT '',
            is_read INTEGER DEFAULT 0,
            has_attachments INTEGER DEFAULT 0,
            customer_id INTEGER,
            opportunity_id INTEGER,
            processed INTEGER DEFAULT 0,
            synced_at TEXT DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS outlook_calendar_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            outlook_event_id TEXT NOT NULL UNIQUE,
            subject TEXT DEFAULT '',
            start_at TEXT DEFAULT '',
            end_at TEXT DEFAULT '',
            organizer_email TEXT DEFAULT '',
            attendee_emails TEXT DEFAULT '',
            location TEXT DEFAULT '',
            web_link TEXT DEFAULT '',
            body_preview TEXT DEFAULT '',
            customer_id INTEGER,
            opportunity_id INTEGER,
            meeting_notes TEXT DEFAULT '',
            synced_at TEXT DEFAULT CURRENT_TIMESTAMP
        );
        """)
        conn.commit()


def outlook_access_allowed():
    try:
        required_password = str(st.secrets.get("CONTROL_TOWER_PASSWORD", "") or "")
    except Exception:
        required_password = ""

    if not required_password:
        st.warning(
            "Outlook entegrasyonu güvenlik nedeniyle kilitli. "
            "Streamlit Secrets içine CONTROL_TOWER_PASSWORD eklenmeden Outlook bağlantısı açılamaz."
        )
        return False

    if st.session_state.get("outlook_admin_unlocked"):
        return True

    password = st.text_input("Outlook entegrasyon şifresi", type="password", key="outlook_admin_password")
    if st.button("Outlook merkezini aç", key="outlook_admin_unlock"):
        if password == required_password:
            st.session_state["outlook_admin_unlocked"] = True
            st.rerun()
        else:
            st.error("Şifre yanlış.")
    return False


def microsoft_settings():
    try:
        client_id = str(st.secrets.get("MICROSOFT_CLIENT_ID", "") or "").strip()
        tenant_id = str(st.secrets.get("MICROSOFT_TENANT_ID", "organizations") or "organizations").strip()
    except Exception:
        client_id = ""
        tenant_id = "organizations"
    return client_id, tenant_id


def match_customer_from_emails(db_path, addresses):
    emails = [str(x or "").lower().strip() for x in addresses if str(x or "").strip()]
    if not emails:
        return None

    known = query_df(db_path, """
        SELECT ct.customer_id, lower(ct.email) AS email
        FROM contacts ct
        WHERE trim(COALESCE(ct.email,''))!=''
        UNION ALL
        SELECT c.id AS customer_id, lower(c.contact_email) AS email
        FROM customers c
        WHERE trim(COALESCE(c.contact_email,''))!=''
    """)

    for email in emails:
        if not known.empty:
            hit = known[known["email"] == email]
            if not hit.empty:
                return int(hit.iloc[0]["customer_id"])

    domains = []
    for email in emails:
        if "@" in email:
            domain = email.split("@", 1)[1]
            if domain and domain not in GENERIC_EMAIL_DOMAINS:
                domains.append(domain)

    for domain in domains:
        if not known.empty:
            mask = known["email"].fillna("").str.endswith("@" + domain)
            hit = known[mask]
            if not hit.empty:
                return int(hit.iloc[0]["customer_id"])
    return None


def sync_messages(db_path, access_token, top=50):
    messages = get_recent_messages(access_token, top=top)
    for message in messages:
        sender = primary_sender(message)
        customer_id = match_customer_from_emails(db_path, [sender["address"]])
        execute(db_path, """
            INSERT INTO outlook_messages
            (outlook_id,conversation_id,subject,sender_name,sender_email,
             received_at,body_preview,web_link,is_read,has_attachments,
             customer_id,synced_at)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
            ON CONFLICT(outlook_id) DO UPDATE SET
              subject=excluded.subject,
              sender_name=excluded.sender_name,
              sender_email=excluded.sender_email,
              received_at=excluded.received_at,
              body_preview=excluded.body_preview,
              web_link=excluded.web_link,
              is_read=excluded.is_read,
              has_attachments=excluded.has_attachments,
              customer_id=COALESCE(outlook_messages.customer_id,excluded.customer_id),
              synced_at=excluded.synced_at
        """, (
            message.get("id",""), message.get("conversationId",""),
            message.get("subject",""), sender["name"], sender["address"],
            message.get("receivedDateTime",""), message.get("bodyPreview",""),
            message.get("webLink",""), 1 if message.get("isRead") else 0,
            1 if message.get("hasAttachments") else 0,
            customer_id, datetime.now().isoformat(timespec="seconds")
        ))
    return len(messages)


def sync_calendar(db_path, access_token):
    events = get_calendar_events(access_token, days_back=1, days_forward=30, top=100)
    for event in events:
        attendees = attendee_addresses(event)
        customer_id = match_customer_from_emails(db_path, attendees)
        organizer = ((event.get("organizer") or {}).get("emailAddress") or {}).get("address","").lower()
        location = ((event.get("location") or {}).get("displayName") or "")
        start = (event.get("start") or {}).get("dateTime","")
        end = (event.get("end") or {}).get("dateTime","")
        execute(db_path, """
            INSERT INTO outlook_calendar_events
            (outlook_event_id,subject,start_at,end_at,organizer_email,attendee_emails,
             location,web_link,body_preview,customer_id,synced_at)
            VALUES (?,?,?,?,?,?,?,?,?,?,?)
            ON CONFLICT(outlook_event_id) DO UPDATE SET
              subject=excluded.subject,start_at=excluded.start_at,end_at=excluded.end_at,
              organizer_email=excluded.organizer_email,attendee_emails=excluded.attendee_emails,
              location=excluded.location,web_link=excluded.web_link,
              body_preview=excluded.body_preview,
              customer_id=COALESCE(outlook_calendar_events.customer_id,excluded.customer_id),
              synced_at=excluded.synced_at
        """, (
            event.get("id",""), event.get("subject",""), start, end, organizer,
            ";".join(attendees), location, event.get("webLink",""),
            event.get("bodyPreview",""), customer_id,
            datetime.now().isoformat(timespec="seconds")
        ))
    return len(events)


def meeting_briefing(db_path, customer_id):
    if not customer_id:
        return "Bu toplantı henüz bir müşteriyle eşleşmedi."
    customer = query_df(db_path, "SELECT * FROM customers WHERE id=?", (int(customer_id),))
    if customer.empty:
        return "Müşteri bulunamadı."
    c = customer.iloc[0]

    opps = query_df(db_path, """
        SELECT product,stage,value,currency,probability,next_action,due_date
        FROM opportunities
        WHERE customer_id=? AND stage NOT IN ('Kaybedildi')
        ORDER BY value DESC LIMIT 8
    """, (int(customer_id),))
    acts = query_df(db_path, """
        SELECT activity_date,activity_type,summary,next_action,next_action_date
        FROM activities
        WHERE customer_id=?
        ORDER BY activity_date DESC,id DESC LIMIT 8
    """, (int(customer_id),))
    rec = query_df(db_path, """
        SELECT invoice_no,due_date,amount-paid_amount AS outstanding,currency
        FROM receivables
        WHERE customer_id=? AND amount-paid_amount>0 AND status!='İptal'
        ORDER BY due_date ASC LIMIT 8
    """, (int(customer_id),))
    quality = query_df(db_path, """
        SELECT case_no,product_name,severity,status,estimated_loss,currency
        FROM quality_cases
        WHERE customer_id=? AND status NOT IN ('Kapandı','İptal')
        ORDER BY id DESC LIMIT 5
    """, (int(customer_id),))

    lines = [
        f"MÜŞTERİ: {c['name']}",
        f"Sektör: {c['sector'] or '-'} | Sorumlu: {c['owner'] or '-'} | Durum: {c['status'] or '-'}",
        "",
        "AÇIK FIRSATLAR:",
    ]
    if opps.empty:
        lines.append("- Açık fırsat yok.")
    else:
        for _, r in opps.iterrows():
            lines.append(
                f"- {r['product']} | {r['stage']} | {float(r['value'] or 0):,.0f} {r['currency']} "
                f"| %{int(r['probability'] or 0)} | Sonraki: {r['next_action'] or '-'}"
            )

    lines.append("")
    lines.append("SON GÖRÜŞMELER:")
    if acts.empty:
        lines.append("- Kayıt yok.")
    else:
        for _, r in acts.iterrows():
            lines.append(f"- {r['activity_date']} {r['activity_type']}: {r['summary']}")

    lines.append("")
    lines.append("AÇIK ALACAK:")
    if rec.empty:
        lines.append("- Açık alacak görünmüyor.")
    else:
        for _, r in rec.iterrows():
            lines.append(
                f"- {r['invoice_no'] or '-'} | Vade {r['due_date']} | "
                f"{float(r['outstanding'] or 0):,.0f} {r['currency']}"
            )

    lines.append("")
    lines.append("AÇIK KALİTE / CLAIM:")
    if quality.empty:
        lines.append("- Açık dosya yok.")
    else:
        for _, r in quality.iterrows():
            lines.append(f"- {r['case_no']} | {r['product_name']} | {r['severity']} | {r['status']}")
    return "\n".join(lines)


def render_outlook_center(db_path):
    init_outlook_tables(db_path)

    st.markdown("### 📨 Outlook + Takvim + Toplantı Merkezi")
    st.caption(
        "Outlook maillerini ve takvimi CRM ile eşleştirir. "
        "AS Control Tower Microsoft Graph üzerinden ayrı yetkilendirilir."
    )

    if not outlook_access_allowed():
        return

    client_id, tenant_id = microsoft_settings()
    if not client_id:
        st.warning("Microsoft bağlantısı henüz programda yapılandırılmadı.")
        st.markdown(
            """
            **Bir defalık Microsoft 365 kurulumu:**
            1. Microsoft Entra içinde bir App Registration oluştur.
            2. Public client flows özelliğini aç.
            3. Delegated izinler olarak User.Read, Mail.Read ve Calendars.Read ver.
            4. Streamlit Secrets içine MICROSOFT_CLIENT_ID ve MICROSOFT_TENANT_ID ekle.

            İlk sürüm sadece okur ve CRM'e bağlar; maili otomatik göndermez.
            """
        )
        return

    st.session_state.setdefault("ms_token_cache", "")
    st.session_state.setdefault("ms_access_token", "")

    token_result, cache_text = get_cached_token(
        client_id, tenant_id, st.session_state.get("ms_token_cache","")
    )
    st.session_state["ms_token_cache"] = cache_text
    if token_result and token_result.get("access_token"):
        st.session_state["ms_access_token"] = token_result["access_token"]

    access_token = st.session_state.get("ms_access_token","")

    if not access_token:
        st.info("Outlook'u bağlamak için Microsoft hesabınla bir kez giriş yap.")
        if st.button("Microsoft bağlantısını başlat", type="primary", key="ms_start"):
            flow, cache_text = start_device_flow(
                client_id, tenant_id,
                serialized_cache=st.session_state.get("ms_token_cache","")
            )
            st.session_state["ms_flow"] = flow
            st.session_state["ms_token_cache"] = cache_text
            st.rerun()

        flow = st.session_state.get("ms_flow")
        if flow:
            st.success(f"Microsoft kodu: {flow.get('user_code','')}")
            verification_uri = flow.get("verification_uri") or "https://microsoft.com/devicelogin"
            st.link_button("Microsoft giriş sayfasını aç", verification_uri)
            st.caption("Kodu girip şirket Outlook hesabınla giriş yaptıktan sonra aşağıdaki düğmeye bas.")
            if st.button("Giriş yaptım - bağlantıyı tamamla", key="ms_finish"):
                result, cache_text = finish_device_flow(
                    client_id, tenant_id, flow,
                    serialized_cache=st.session_state.get("ms_token_cache","")
                )
                st.session_state["ms_token_cache"] = cache_text
                if result.get("access_token"):
                    st.session_state["ms_access_token"] = result["access_token"]
                    st.session_state.pop("ms_flow", None)
                    st.success("Outlook bağlantısı kuruldu.")
                    st.rerun()
                else:
                    st.error(result.get("error_description") or "Microsoft bağlantısı tamamlanamadı.")
        return

    try:
        profile = get_profile(access_token)
        mailbox = (profile.get("mail") or profile.get("userPrincipalName") or "").lower()
        try:
            allowed_mailbox = str(st.secrets.get("MICROSOFT_ALLOWED_EMAIL", "") or "").lower().strip()
        except Exception:
            allowed_mailbox = ""
        if allowed_mailbox and mailbox != allowed_mailbox:
            st.session_state["ms_access_token"] = ""
            st.session_state["ms_token_cache"] = ""
            st.error("Bu Microsoft hesabının AS Control Tower'a bağlanmasına izin verilmemiş.")
            return
        st.success(
            f"Bağlı Outlook: {profile.get('displayName','')} · {mailbox}"
        )
    except Exception as exc:
        st.warning(f"Outlook oturumu yenilenmeli: {exc}")
        if st.button("Outlook oturumunu sıfırla"):
            st.session_state["ms_access_token"] = ""
            st.session_state["ms_token_cache"] = ""
            st.rerun()
        return

    mail_tab, meeting_tab = st.tabs(["📥 Outlook Mailleri", "📅 Toplantılar"])

    with mail_tab:
        c1,c2 = st.columns(2)
        if c1.button("Son 50 maili senkronize et", type="primary", use_container_width=True):
            try:
                n = sync_messages(db_path, access_token, 50)
                st.success(f"{n} mail kontrol edildi / senkronize edildi.")
                st.rerun()
            except Exception as exc:
                st.error(f"Outlook mail senkronu başarısız: {exc}")
        if c2.button("Outlook bağlantısını kapat", use_container_width=True):
            st.session_state["ms_access_token"] = ""
            st.session_state["ms_token_cache"] = ""
            st.rerun()

        mails = query_df(db_path, """
            SELECT om.id,om.received_at AS tarih,om.sender_name AS gönderen,
                   om.sender_email AS email,om.subject AS konu,c.name AS müşteri,
                   om.is_read AS okundu,om.has_attachments AS ek,om.processed AS işlendi,
                   om.body_preview AS önizleme,om.web_link
            FROM outlook_messages om
            LEFT JOIN customers c ON c.id=om.customer_id
            ORDER BY om.received_at DESC,om.id DESC
            LIMIT 100
        """)
        st.dataframe(mails,use_container_width=True,hide_index=True)

        if not mails.empty:
            mid=st.selectbox(
                "CRM'e işlenecek mail",
                mails["id"].tolist(),
                format_func=lambda x:(
                    f"{mails.loc[mails['id']==x,'gönderen'].iloc[0]} · "
                    f"{mails.loc[mails['id']==x,'konu'].iloc[0]}"
                ),
                key="outlook_mail_select"
            )
            raw=query_df(db_path, "SELECT * FROM outlook_messages WHERE id=?", (int(mid),)).iloc[0]
            customers=query_df(db_path, "SELECT id,name FROM customers ORDER BY name")
            options=["— Eşleştirme yok —"]+customers["name"].tolist()
            default_idx=0
            if raw["customer_id"]:
                hit=customers[customers["id"]==int(raw["customer_id"])]
                if not hit.empty and hit.iloc[0]["name"] in options:
                    default_idx=options.index(hit.iloc[0]["name"])
            cname=st.selectbox("Müşteri",options,index=default_idx,key="outlook_mail_customer")
            summary=st.text_area(
                "CRM görüşme notu",
                value=f"Outlook: {raw['subject']}\n{raw['body_preview'] or ''}",
                key="outlook_mail_activity"
            )
            next_action=st.text_input("Sonraki aksiyon",key="outlook_mail_action")
            due=st.date_input("Takip tarihi",value=date.today()+timedelta(days=2),key="outlook_mail_due")
            if st.button("Maili CRM'e işle",type="primary",key="outlook_mail_process"):
                if cname=="— Eşleştirme yok —":
                    st.warning("Önce müşteriyi seç.")
                else:
                    cid=int(customers.loc[customers["name"]==cname,"id"].iloc[0])
                    execute(db_path, "UPDATE outlook_messages SET customer_id=?,processed=1 WHERE id=?", (cid,int(mid)))
                    execute(db_path, """INSERT INTO activities
                        (customer_id,activity_type,activity_date,summary,next_action,next_action_date,owner)
                        VALUES (?,'E-posta',?,?,?,?,?)""",
                        (cid,str(date.today()),summary,next_action,str(due),""))
                    if next_action.strip():
                        execute(db_path, """INSERT INTO tasks
                            (title,related_to,owner,priority,due_date,status,notes)
                            VALUES (?,?,?,'Orta',?,'Açık',?)""",
                            (next_action,cname,"",str(due),f"Outlook mailinden: {raw['subject']}"))
                    st.success("Mail CRM'e işlendi.")
                    st.rerun()

    with meeting_tab:
        if st.button("Outlook takvimini senkronize et",type="primary",key="outlook_calendar_sync"):
            try:
                n=sync_calendar(db_path, access_token)
                st.success(f"{n} toplantı kontrol edildi / senkronize edildi.")
                st.rerun()
            except Exception as exc:
                st.error(f"Outlook takvim senkronu başarısız: {exc}")

        meetings=query_df(db_path, """
            SELECT e.id,e.subject AS toplantı,e.start_at AS başlangıç,e.end_at AS bitiş,
                   e.location AS yer,c.name AS müşteri,e.organizer_email AS organizatör,
                   e.attendee_emails AS katılımcılar,e.web_link
            FROM outlook_calendar_events e
            LEFT JOIN customers c ON c.id=e.customer_id
            ORDER BY e.start_at ASC,e.id ASC
            LIMIT 100
        """)
        st.dataframe(meetings,use_container_width=True,hide_index=True)

        if not meetings.empty:
            eid=st.selectbox(
                "Toplantı seç",
                meetings["id"].tolist(),
                format_func=lambda x:(
                    f"{meetings.loc[meetings['id']==x,'başlangıç'].iloc[0]} · "
                    f"{meetings.loc[meetings['id']==x,'toplantı'].iloc[0]}"
                ),
                key="outlook_meeting_select"
            )
            erow=query_df(db_path, "SELECT * FROM outlook_calendar_events WHERE id=?", (int(eid),)).iloc[0]
            customers=query_df(db_path, "SELECT id,name FROM customers ORDER BY name")
            options=["— Eşleştirme yok —"]+customers["name"].tolist()
            default_idx=0
            if erow["customer_id"]:
                hit=customers[customers["id"]==int(erow["customer_id"])]
                if not hit.empty and hit.iloc[0]["name"] in options:
                    default_idx=options.index(hit.iloc[0]["name"])
            cname=st.selectbox("Toplantı müşterisi",options,index=default_idx,key="meeting_customer")
            if cname!="— Eşleştirme yok —":
                cid=int(customers.loc[customers["name"]==cname,"id"].iloc[0])
                execute(db_path, "UPDATE outlook_calendar_events SET customer_id=? WHERE id=?", (cid,int(eid)))
                briefing=meeting_briefing(db_path,cid)
                st.text_area("Toplantı öncesi briefing",value=briefing,height=320,key="meeting_briefing")
                notes=st.text_area("Toplantı sonrası not",key="meeting_notes")
                followup=st.text_input("Toplantı sonrası aksiyon",key="meeting_followup")
                followup_date=st.date_input("Aksiyon tarihi",value=date.today()+timedelta(days=2),key="meeting_followup_date")
                if st.button("Toplantı notunu CRM'e kaydet",type="primary",key="meeting_save"):
                    if notes.strip():
                        execute(db_path, """INSERT INTO activities
                            (customer_id,activity_type,activity_date,summary,next_action,next_action_date,owner)
                            VALUES (?,'Toplantı',?,?,?,?,?)""",
                            (cid,str(date.today()),notes,followup,str(followup_date),""))
                        execute(db_path, "UPDATE outlook_calendar_events SET meeting_notes=? WHERE id=?", (notes,int(eid)))
                    if followup.strip():
                        execute(db_path, """INSERT INTO tasks
                            (title,related_to,owner,priority,due_date,status,notes)
                            VALUES (?,?,?,'Yüksek',?,'Açık',?)""",
                            (followup,cname,"",str(followup_date),f"Outlook toplantısından: {erow['subject']}"))
                    st.success("Toplantı notu ve aksiyon kaydedildi.")
                    st.rerun()
