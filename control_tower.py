import sqlite3
from datetime import date, datetime, timedelta
from pathlib import Path

import pandas as pd
import streamlit as st

DB_PATH = Path(__file__).with_name("as_control_tower.db")

STAGES = [
    "Lead", "Temas", "Numune", "Deneme", "Teklif", "Pazarlık",
    "Sipariş", "Kazanıldı", "Kaybedildi", "Problem / Koruma",
]

STAGE_PROBABILITY = {
    "Lead": 10,
    "Temas": 20,
    "Numune": 30,
    "Deneme": 45,
    "Teklif": 60,
    "Pazarlık": 75,
    "Sipariş": 90,
    "Kazanıldı": 100,
    "Kaybedildi": 0,
    "Problem / Koruma": 50,
}

ACTIVITY_TYPES = [
    "Telefon", "E-posta", "WhatsApp", "Toplantı", "Numune",
    "Teklif", "Teknik görüşme", "Ziyaret", "Not",
]


def get_conn():
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


def execute(sql, params=()):
    with get_conn() as conn:
        conn.execute(sql, params)
        conn.commit()


def query_df(sql, params=()):
    with get_conn() as conn:
        return pd.read_sql_query(sql, conn, params=params)


def ensure_column(conn, table, column, definition):
    columns = {row[1] for row in conn.execute(f"PRAGMA table_info({table})").fetchall()}
    if column not in columns:
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")


def init_db():
    with get_conn() as conn:
        conn.executescript("""
        CREATE TABLE IF NOT EXISTS customers (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            country TEXT DEFAULT '',
            sector TEXT DEFAULT '',
            status TEXT DEFAULT 'Potansiyel',
            owner TEXT DEFAULT '',
            annual_potential REAL DEFAULT 0,
            currency TEXT DEFAULT 'EUR',
            contact_name TEXT DEFAULT '',
            contact_email TEXT DEFAULT '',
            phone TEXT DEFAULT '',
            source TEXT DEFAULT '',
            notes TEXT DEFAULT '',
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS opportunities (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            customer_id INTEGER,
            product TEXT NOT NULL,
            stage TEXT DEFAULT 'Lead',
            value REAL DEFAULT 0,
            currency TEXT DEFAULT 'EUR',
            probability INTEGER DEFAULT 10,
            next_action TEXT DEFAULT '',
            due_date TEXT DEFAULT '',
            owner TEXT DEFAULT '',
            notes TEXT DEFAULT '',
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(customer_id) REFERENCES customers(id)
        );

        CREATE TABLE IF NOT EXISTS tasks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL,
            related_to TEXT DEFAULT '',
            owner TEXT DEFAULT '',
            priority TEXT DEFAULT 'Orta',
            due_date TEXT DEFAULT '',
            status TEXT DEFAULT 'Açık',
            notes TEXT DEFAULT '',
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS contacts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            customer_id INTEGER NOT NULL,
            name TEXT NOT NULL,
            title TEXT DEFAULT '',
            department TEXT DEFAULT '',
            email TEXT DEFAULT '',
            phone TEXT DEFAULT '',
            is_primary INTEGER DEFAULT 0,
            notes TEXT DEFAULT '',
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(customer_id) REFERENCES customers(id)
        );

        CREATE TABLE IF NOT EXISTS activities (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            customer_id INTEGER NOT NULL,
            opportunity_id INTEGER,
            activity_type TEXT DEFAULT 'Not',
            activity_date TEXT DEFAULT '',
            summary TEXT NOT NULL,
            next_action TEXT DEFAULT '',
            next_action_date TEXT DEFAULT '',
            owner TEXT DEFAULT '',
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(customer_id) REFERENCES customers(id),
            FOREIGN KEY(opportunity_id) REFERENCES opportunities(id)
        );

        CREATE TABLE IF NOT EXISTS opportunity_stage_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            opportunity_id INTEGER NOT NULL,
            old_stage TEXT DEFAULT '',
            new_stage TEXT DEFAULT '',
            changed_at TEXT DEFAULT CURRENT_TIMESTAMP,
            owner TEXT DEFAULT '',
            note TEXT DEFAULT '',
            FOREIGN KEY(opportunity_id) REFERENCES opportunities(id)
        );
        """)

        ensure_column(conn, "opportunities", "last_contact_date", "TEXT DEFAULT ''")
        ensure_column(conn, "opportunities", "expected_close_date", "TEXT DEFAULT ''")
        ensure_column(conn, "opportunities", "lost_reason", "TEXT DEFAULT ''")
        ensure_column(conn, "opportunities", "updated_at", "TEXT DEFAULT ''")
        conn.commit()


def seed_once():
    count = int(query_df("SELECT COUNT(*) n FROM customers").iloc[0]["n"])
    if count:
        return

    execute(
        """INSERT INTO customers
        (name,country,sector,status,owner,annual_potential,currency,source,notes)
        VALUES (?,?,?,?,?,?,?,?,?)""",
        ("Ülker / Pladis", "Türkiye", "Bisküvi / Unlu Mamul", "Aktif", "Serkan",
         1500000, "EUR", "Başlangıç", "Stratejik müşteri; kalite ve tedarik takibi önemli.")
    )
    execute(
        """INSERT INTO customers
        (name,country,sector,status,owner,annual_potential,currency,source,notes)
        VALUES (?,?,?,?,?,?,?,?,?)""",
        ("Pakmaya", "Türkiye", "Fırıncılık / Maya", "Potansiyel", "Satış",
         250000, "EUR", "Başlangıç", "Mokaero 22 endüstriyel deneme fırsatı.")
    )

    c1 = int(query_df("SELECT id FROM customers WHERE name='Ülker / Pladis'").iloc[0]["id"])
    c2 = int(query_df("SELECT id FROM customers WHERE name='Pakmaya'").iloc[0]["id"])

    execute(
        """INSERT INTO opportunities
        (customer_id,product,stage,value,currency,probability,next_action,due_date,
         owner,notes,last_contact_date,expected_close_date,updated_at)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (c1, "Pantur 1250", "Problem / Koruma", 350000, "EUR", 70,
         "Tedarikçi teknik/ticari çözümünü netleştir", str(date.today() + timedelta(days=2)),
         "Serkan", "Müşteri kaybı ve claim riski.", str(date.today()),
         str(date.today() + timedelta(days=20)), datetime.now().isoformat(timespec="seconds"))
    )
    execute(
        """INSERT INTO opportunities
        (customer_id,product,stage,value,currency,probability,next_action,due_date,
         owner,notes,last_contact_date,expected_close_date,updated_at)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (c2, "Mokaero 22 Topping Base", "Deneme", 120000, "EUR", 55,
         "Endüstriyel deneme sonucunu takip et", str(date.today() + timedelta(days=3)),
         "Satış", "", str(date.today()), str(date.today() + timedelta(days=30)),
         datetime.now().isoformat(timespec="seconds"))
    )
    execute(
        """INSERT INTO tasks
        (title,related_to,owner,priority,due_date,status,notes)
        VALUES (?,?,?,?,?,'Açık',?)""",
        ("Pantur 1250 için çözümü netleştir", "Ülker / Pladis", "Serkan",
         "Kritik", str(date.today() + timedelta(days=2)), "")
    )


def import_supplier_results():
    df = st.session_state.get("supplier_results", pd.DataFrame())
    if not isinstance(df, pd.DataFrame) or df.empty:
        return 0

    added = 0
    for _, row in df.iterrows():
        name = str(row.get("Firma", "") or "").strip()
        if not name:
            continue
        exists = int(query_df(
            "SELECT COUNT(*) n FROM customers WHERE lower(name)=lower(?)", (name,)
        ).iloc[0]["n"])
        if exists:
            continue
        execute(
            """INSERT INTO customers
            (name,country,sector,status,contact_email,phone,source,notes)
            VALUES (?,?,?,?,?,?,?,?)""",
            (
                name,
                str(row.get("Üretici Ülkesi", "") or row.get("Hedef Pazar", "") or ""),
                "Tedarikçi / Üretici",
                "Potansiyel",
                str(row.get("Satış / Export E-mail", "") or ""),
                str(row.get("Telefon", "") or ""),
                "Üretici Bulucu",
                str(row.get("Kaynak URL", "") or ""),
            )
        )
        added += 1
    return added


def import_acquisition_results():
    df = st.session_state.get("acq_results", pd.DataFrame())
    if not isinstance(df, pd.DataFrame) or df.empty:
        return 0

    added = 0
    for _, row in df.iterrows():
        name = str(row.get("Başlık", "") or "").strip()
        if not name:
            continue
        exists = int(query_df(
            "SELECT COUNT(*) n FROM customers WHERE lower(name)=lower(?)", (name,)
        ).iloc[0]["n"])
        if exists:
            continue
        execute(
            """INSERT INTO customers
            (name,country,sector,status,contact_email,phone,source,notes)
            VALUES (?,?,?,?,?,?,?,?)""",
            (
                name,
                str(row.get("Ülke", "") or ""),
                str(row.get("Sektör", "") or ""),
                "Satın Alma Adayı",
                str(row.get("E-posta", "") or ""),
                str(row.get("Telefon", "") or ""),
                "Firma Satın Alma",
                str(row.get("İlan / kaynak URL", "") or ""),
            )
        )
        added += 1
    return added


def money(v, currency="EUR"):
    try:
        return f"{float(v):,.0f} {currency}"
    except Exception:
        return f"0 {currency}"


def add_activity(customer_id, opportunity_id, activity_type, activity_date, summary,
                 next_action, next_action_date, owner):
    execute(
        """INSERT INTO activities
        (customer_id,opportunity_id,activity_type,activity_date,summary,
         next_action,next_action_date,owner)
        VALUES (?,?,?,?,?,?,?,?)""",
        (
            int(customer_id),
            int(opportunity_id) if opportunity_id else None,
            activity_type,
            str(activity_date),
            summary.strip(),
            next_action.strip(),
            str(next_action_date) if next_action_date else "",
            owner.strip(),
        )
    )
    if opportunity_id:
        execute(
            """UPDATE opportunities
               SET last_contact_date=?, next_action=?, due_date=?, updated_at=?
               WHERE id=?""",
            (
                str(activity_date),
                next_action.strip(),
                str(next_action_date) if next_action_date else "",
                datetime.now().isoformat(timespec="seconds"),
                int(opportunity_id),
            )
        )


def update_opportunity_stage(opportunity_id, new_stage, probability, next_action,
                             due_date, owner, expected_close_date, lost_reason, note):
    row = query_df("SELECT stage FROM opportunities WHERE id=?", (int(opportunity_id),))
    if row.empty:
        return
    old_stage = str(row.iloc[0]["stage"])
    execute(
        """UPDATE opportunities
           SET stage=?, probability=?, next_action=?, due_date=?, owner=?,
               expected_close_date=?, lost_reason=?, updated_at=?
           WHERE id=?""",
        (
            new_stage, int(probability), next_action.strip(), str(due_date), owner.strip(),
            str(expected_close_date) if expected_close_date else "",
            lost_reason.strip(), datetime.now().isoformat(timespec="seconds"),
            int(opportunity_id),
        )
    )
    if old_stage != new_stage:
        execute(
            """INSERT INTO opportunity_stage_history
            (opportunity_id,old_stage,new_stage,owner,note)
            VALUES (?,?,?,?,?)""",
            (int(opportunity_id), old_stage, new_stage, owner.strip(), note.strip())
        )


def render_control_tower():
    init_db()
    seed_once()

    st.subheader("🧭 AS CONTROL TOWER")
    st.caption("CRM • satış hunisi • takip • görev • yönetici karar merkezi")

    dashboard, customers_tab, pipeline_tab, followup_tab, tasks_tab, ceo_tab = st.tabs(
        [
            "📊 Yönetici Paneli",
            "👥 CRM / Müşteri 360",
            "💰 Satış Pipeline",
            "📞 Takip Merkezi",
            "✅ Görevler",
            "🎯 Serkan Ekranı",
        ]
    )

    with dashboard:
        customer_count = int(query_df("SELECT COUNT(*) n FROM customers").iloc[0]["n"])
        active_opps = int(query_df(
            "SELECT COUNT(*) n FROM opportunities WHERE stage NOT IN ('Kazanıldı','Kaybedildi')"
        ).iloc[0]["n"])
        opp = query_df(
            "SELECT value, probability FROM opportunities WHERE stage NOT IN ('Kaybedildi')"
        )
        weighted = float((opp["value"] * opp["probability"] / 100).sum()) if not opp.empty else 0
        won = float(query_df(
            "SELECT COALESCE(SUM(value),0) v FROM opportunities WHERE stage='Kazanıldı'"
        ).iloc[0]["v"])
        overdue_followups = int(query_df(
            """SELECT COUNT(*) n FROM opportunities
               WHERE stage NOT IN ('Kazanıldı','Kaybedildi')
                 AND due_date != '' AND due_date < ?""",
            (str(date.today()),)
        ).iloc[0]["n"])

        m1, m2, m3, m4, m5 = st.columns(5)
        m1.metric("CRM kayıtları", customer_count)
        m2.metric("Aktif fırsat", active_opps)
        m3.metric("Ağırlıklı pipeline", money(weighted))
        m4.metric("Kazanılan", money(won))
        m5.metric("Geciken takip", overdue_followups)

        st.markdown("#### Satış hunisi")
        funnel = query_df("""
            SELECT stage AS aşama,
                   COUNT(*) AS fırsat_sayısı,
                   ROUND(SUM(value),0) AS toplam_değer,
                   ROUND(SUM(value * probability / 100.0),0) AS ağırlıklı_değer
            FROM opportunities
            GROUP BY stage
        """)
        if not funnel.empty:
            order = {stage: i for i, stage in enumerate(STAGES)}
            funnel["_order"] = funnel["aşama"].map(order).fillna(999)
            funnel = funnel.sort_values("_order").drop(columns=["_order"])
        st.dataframe(funnel, use_container_width=True, hide_index=True)

        st.markdown("#### Bugün / gecikmiş satış takipleri")
        due = query_df("""
            SELECT o.id, c.name AS müşteri, o.product AS ürün, o.stage AS aşama,
                   o.next_action AS sonraki_aksiyon, o.due_date AS takip_tarihi,
                   o.owner AS sorumlu
            FROM opportunities o
            LEFT JOIN customers c ON c.id=o.customer_id
            WHERE o.stage NOT IN ('Kazanıldı','Kaybedildi')
              AND o.due_date != '' AND o.due_date <= ?
            ORDER BY o.due_date ASC
            LIMIT 12
        """, (str(date.today()),))
        st.dataframe(due, use_container_width=True, hide_index=True)

        st.markdown("#### Arama sonuçlarını sisteme al")
        i1, i2 = st.columns(2)
        with i1:
            if st.button("Son Üretici Bulucu sonuçlarını CRM'e aktar", use_container_width=True):
                n = import_supplier_results()
                st.success(f"{n} yeni kayıt CRM'e aktarıldı.")
        with i2:
            if st.button("Son Satılık Firma sonuçlarını CRM'e aktar", use_container_width=True):
                n = import_acquisition_results()
                st.success(f"{n} yeni kayıt CRM'e aktarıldı.")

    with customers_tab:
        customers = query_df("SELECT id, name FROM customers ORDER BY name")
        if customers.empty:
            st.info("Henüz CRM kaydı yok.")
        else:
            selected_customer_name = st.selectbox(
                "Müşteri / şirket seç",
                customers["name"].tolist(),
                key="ct_customer_360_select",
            )
            customer_id = int(
                customers.loc[customers["name"] == selected_customer_name, "id"].iloc[0]
            )
            customer = query_df("SELECT * FROM customers WHERE id=?", (customer_id,)).iloc[0]

            h1, h2, h3, h4 = st.columns(4)
            h1.metric("Durum", customer["status"] or "-")
            h2.metric("Ülke", customer["country"] or "-")
            h3.metric("Sektör", customer["sector"] or "-")
            h4.metric("Sorumlu", customer["owner"] or "-")

            st.caption(
                f"Kaynak: {customer['source'] or '-'} · "
                f"Genel e-posta: {customer['contact_email'] or '-'} · "
                f"Telefon: {customer['phone'] or '-'}"
            )
            if customer["notes"]:
                st.info(customer["notes"])

            ctab1, ctab2, ctab3, ctab4 = st.tabs(
                ["Fırsatlar", "Görüşme Geçmişi", "Kontaklar", "Kartı Düzenle"]
            )

            with ctab1:
                customer_opps = query_df("""
                    SELECT id, product AS ürün, stage AS aşama, value AS değer,
                           currency AS para, probability AS olasılık,
                           next_action AS sonraki_aksiyon, due_date AS takip_tarihi,
                           owner AS sorumlu, last_contact_date AS son_görüşme
                    FROM opportunities
                    WHERE customer_id=?
                    ORDER BY created_at DESC
                """, (customer_id,))
                st.dataframe(customer_opps, use_container_width=True, hide_index=True)

            with ctab2:
                activities = query_df("""
                    SELECT a.activity_date AS tarih, a.activity_type AS tip,
                           a.summary AS görüşme_notu, o.product AS fırsat,
                           a.next_action AS sonraki_aksiyon,
                           a.next_action_date AS takip_tarihi, a.owner AS sorumlu
                    FROM activities a
                    LEFT JOIN opportunities o ON o.id=a.opportunity_id
                    WHERE a.customer_id=?
                    ORDER BY a.activity_date DESC, a.id DESC
                """, (customer_id,))
                st.dataframe(activities, use_container_width=True, hide_index=True)

                st.markdown("##### Yeni görüşme / temas kaydı")
                opp_choices = query_df(
                    "SELECT id, product, stage FROM opportunities WHERE customer_id=? ORDER BY id DESC",
                    (customer_id,)
                )
                opp_map = {"Genel müşteri görüşmesi": None}
                for _, r in opp_choices.iterrows():
                    opp_map[f"{r['product']} · {r['stage']}"] = int(r["id"])

                with st.form("ct_activity_form", clear_on_submit=True):
                    activity_type = st.selectbox("Temas tipi", ACTIVITY_TYPES)
                    opportunity_label = st.selectbox("İlgili fırsat", list(opp_map.keys()))
                    a1, a2 = st.columns(2)
                    activity_date = a1.date_input("Görüşme tarihi", value=date.today())
                    owner = a2.text_input("Görüşmeyi yapan", value=customer["owner"] or "")
                    summary = st.text_area(
                        "Ne konuşuldu? *",
                        placeholder="Müşteri ne dedi, hangi fiyat/numune/teknik konu konuşuldu?"
                    )
                    next_action = st.text_input(
                        "Sonraki aksiyon",
                        placeholder="Örn: 50 kg numune gönder / fiyat revize et / Cuma ara"
                    )
                    next_action_date = st.date_input(
                        "Takip tarihi",
                        value=date.today() + timedelta(days=3)
                    )
                    create_task = st.checkbox("Bu takip için görev de oluştur", value=True)
                    if st.form_submit_button("Görüşmeyi kaydet", type="primary") and summary.strip():
                        opp_id = opp_map[opportunity_label]
                        add_activity(
                            customer_id, opp_id, activity_type, activity_date, summary,
                            next_action, next_action_date, owner
                        )
                        if create_task and next_action.strip():
                            execute(
                                """INSERT INTO tasks
                                (title,related_to,owner,priority,due_date,status,notes)
                                VALUES (?,?,?,?,?,'Açık',?)""",
                                (
                                    next_action.strip(), selected_customer_name, owner,
                                    "Orta", str(next_action_date),
                                    f"CRM görüşme kaydından oluşturuldu: {summary[:180]}"
                                )
                            )
                        st.success("Görüşme ve takip kaydedildi.")
                        st.rerun()

            with ctab3:
                contacts = query_df("""
                    SELECT id, name AS ad_soyad, title AS ünvan, department AS departman,
                           email, phone AS telefon,
                           CASE WHEN is_primary=1 THEN 'Evet' ELSE '' END AS ana_kontak,
                           notes AS notlar
                    FROM contacts
                    WHERE customer_id=?
                    ORDER BY is_primary DESC, name
                """, (customer_id,))
                st.dataframe(contacts, use_container_width=True, hide_index=True)

                with st.form("ct_contact_form", clear_on_submit=True):
                    name = st.text_input("Ad soyad *")
                    x1, x2 = st.columns(2)
                    title = x1.text_input("Ünvan")
                    department = x2.text_input("Departman")
                    x3, x4 = st.columns(2)
                    email = x3.text_input("E-posta")
                    phone = x4.text_input("Telefon")
                    is_primary = st.checkbox("Ana kontak")
                    notes = st.text_area("Not")
                    if st.form_submit_button("Kontak ekle") and name.strip():
                        if is_primary:
                            execute("UPDATE contacts SET is_primary=0 WHERE customer_id=?", (customer_id,))
                        execute(
                            """INSERT INTO contacts
                            (customer_id,name,title,department,email,phone,is_primary,notes)
                            VALUES (?,?,?,?,?,?,?,?)""",
                            (
                                customer_id, name.strip(), title, department, email,
                                phone, 1 if is_primary else 0, notes
                            )
                        )
                        st.success("Kontak eklendi.")
                        st.rerun()

            with ctab4:
                with st.form("ct_edit_customer"):
                    e1, e2 = st.columns(2)
                    country = e1.text_input("Ülke", value=customer["country"] or "")
                    sector = e2.text_input("Sektör", value=customer["sector"] or "")
                    e3, e4 = st.columns(2)
                    statuses = ["Potansiyel", "Aktif", "Riskli", "Pasif", "Satın Alma Adayı"]
                    default_status = customer["status"] if customer["status"] in statuses else "Potansiyel"
                    status = e3.selectbox("Durum", statuses, index=statuses.index(default_status))
                    owner = e4.text_input("Sorumlu", value=customer["owner"] or "")
                    e5, e6 = st.columns(2)
                    potential = e5.number_input(
                        "Yıllık potansiyel",
                        min_value=0.0,
                        value=float(customer["annual_potential"] or 0),
                        step=1000.0
                    )
                    currency = e6.selectbox(
                        "Para",
                        ["EUR", "USD", "GBP", "TRY"],
                        index=["EUR", "USD", "GBP", "TRY"].index(
                            customer["currency"] if customer["currency"] in ["EUR", "USD", "GBP", "TRY"] else "EUR"
                        )
                    )
                    notes = st.text_area("Not", value=customer["notes"] or "")
                    if st.form_submit_button("Müşteri kartını güncelle"):
                        execute(
                            """UPDATE customers
                               SET country=?,sector=?,status=?,owner=?,
                                   annual_potential=?,currency=?,notes=?
                               WHERE id=?""",
                            (country, sector, status, owner, potential, currency, notes, customer_id)
                        )
                        st.success("Müşteri kartı güncellendi.")
                        st.rerun()

        st.divider()
        with st.expander("Yeni müşteri / şirket ekle"):
            with st.form("ct_customer_form", clear_on_submit=True):
                name = st.text_input("Firma adı *", key="ct_customer_name")
                c1, c2 = st.columns(2)
                country = c1.text_input("Ülke", key="ct_customer_country")
                sector = c2.text_input("Sektör", key="ct_customer_sector")
                c3, c4 = st.columns(2)
                status = c3.selectbox(
                    "Durum", ["Potansiyel", "Aktif", "Riskli", "Pasif", "Satın Alma Adayı"]
                )
                owner = c4.text_input("Sorumlu", key="ct_customer_owner")
                contact = st.text_input("İlk kontak kişi", key="ct_customer_contact")
                email = st.text_input("Genel / ilk e-posta", key="ct_customer_email")
                phone = st.text_input("Telefon", key="ct_customer_phone")
                notes = st.text_area("Not", key="ct_customer_notes")
                if st.form_submit_button("Kaydet", type="primary") and name.strip():
                    execute(
                        """INSERT INTO customers
                        (name,country,sector,status,owner,contact_name,contact_email,phone,source,notes)
                        VALUES (?,?,?,?,?,?,?,?,?,?)""",
                        (name.strip(), country, sector, status, owner, contact, email, phone, "Manuel", notes)
                    )
                    new_id = int(query_df(
                        "SELECT id FROM customers WHERE name=? ORDER BY id DESC LIMIT 1",
                        (name.strip(),)
                    ).iloc[0]["id"])
                    if contact.strip():
                        execute(
                            """INSERT INTO contacts
                            (customer_id,name,email,phone,is_primary)
                            VALUES (?,?,?,?,1)""",
                            (new_id, contact.strip(), email, phone)
                        )
                    st.success("CRM kaydı eklendi.")
                    st.rerun()

    with pipeline_tab:
        pipeline = query_df("""
            SELECT o.id, c.name AS müşteri, o.product AS ürün, o.stage AS aşama,
                   o.value AS değer, o.currency AS para, o.probability AS olasılık,
                   o.next_action AS sonraki_aksiyon, o.due_date AS takip_tarihi,
                   o.last_contact_date AS son_görüşme, o.expected_close_date AS kapanış_tahmini,
                   o.owner AS sorumlu
            FROM opportunities o
            LEFT JOIN customers c ON c.id=o.customer_id
            ORDER BY CASE o.stage
                WHEN 'Problem / Koruma' THEN 1
                WHEN 'Pazarlık' THEN 2
                WHEN 'Teklif' THEN 3
                WHEN 'Deneme' THEN 4
                WHEN 'Numune' THEN 5
                WHEN 'Temas' THEN 6
                WHEN 'Lead' THEN 7
                WHEN 'Sipariş' THEN 8
                WHEN 'Kazanıldı' THEN 9
                ELSE 10 END,
                o.value DESC
        """)
        st.dataframe(pipeline, use_container_width=True, hide_index=True)

        ptab1, ptab2 = st.tabs(["Fırsatı Güncelle", "Yeni Fırsat"])

        with ptab1:
            if pipeline.empty:
                st.info("Henüz fırsat yok.")
            else:
                opp_id = st.selectbox(
                    "Fırsat seç",
                    pipeline["id"].tolist(),
                    format_func=lambda x: (
                        f"{pipeline.loc[pipeline['id']==x, 'müşteri'].iloc[0]} · "
                        f"{pipeline.loc[pipeline['id']==x, 'ürün'].iloc[0]} · "
                        f"{pipeline.loc[pipeline['id']==x, 'aşama'].iloc[0]}"
                    ),
                    key="ct_pipeline_edit_select"
                )
                row = query_df("""
                    SELECT o.*, c.name AS customer_name
                    FROM opportunities o
                    LEFT JOIN customers c ON c.id=o.customer_id
                    WHERE o.id=?
                """, (int(opp_id),)).iloc[0]

                with st.form("ct_pipeline_edit"):
                    old_stage = row["stage"] if row["stage"] in STAGES else "Lead"
                    stage = st.selectbox("Aşama", STAGES, index=STAGES.index(old_stage))
                    auto_probability = st.checkbox("Aşamaya göre olasılığı otomatik ayarla", value=True)
                    probability = st.slider(
                        "Olasılık %",
                        0, 100,
                        STAGE_PROBABILITY[stage] if auto_probability else int(row["probability"] or 0),
                        5
                    )
                    next_action = st.text_input(
                        "Sonraki aksiyon", value=row["next_action"] or ""
                    )
                    d1, d2 = st.columns(2)
                    due_default = (
                        datetime.strptime(row["due_date"], "%Y-%m-%d").date()
                        if row["due_date"] else date.today() + timedelta(days=3)
                    )
                    close_default = (
                        datetime.strptime(row["expected_close_date"], "%Y-%m-%d").date()
                        if row["expected_close_date"] else date.today() + timedelta(days=30)
                    )
                    due_date = d1.date_input("Takip tarihi", value=due_default)
                    expected_close = d2.date_input("Tahmini kapanış", value=close_default)
                    owner = st.text_input("Sorumlu", value=row["owner"] or "")
                    lost_reason = st.text_input(
                        "Kaybedilme nedeni",
                        value=row["lost_reason"] or "",
                        disabled=stage != "Kaybedildi"
                    )
                    note = st.text_area(
                        "Aşama değişiklik notu",
                        placeholder="Örn: numune olumlu, fiyat teklifine geçildi."
                    )
                    create_task = st.checkbox("Sonraki aksiyon için görev oluştur", value=True)

                    if st.form_submit_button("Fırsatı güncelle", type="primary"):
                        final_probability = STAGE_PROBABILITY[stage] if auto_probability else probability
                        update_opportunity_stage(
                            opp_id, stage, final_probability, next_action, due_date,
                            owner, expected_close, lost_reason, note
                        )
                        if create_task and next_action.strip() and stage not in ["Kazanıldı", "Kaybedildi"]:
                            existing = int(query_df(
                                """SELECT COUNT(*) n FROM tasks
                                   WHERE title=? AND related_to=? AND status!='Tamamlandı'""",
                                (next_action.strip(), row["customer_name"])
                            ).iloc[0]["n"])
                            if not existing:
                                execute(
                                    """INSERT INTO tasks
                                    (title,related_to,owner,priority,due_date,status,notes)
                                    VALUES (?,?,?,?,?,'Açık',?)""",
                                    (
                                        next_action.strip(), row["customer_name"], owner,
                                        "Yüksek" if stage in ["Teklif", "Pazarlık", "Problem / Koruma"] else "Orta",
                                        str(due_date),
                                        f"Satış pipeline fırsatı #{opp_id}"
                                    )
                                )
                        st.success("Fırsat güncellendi.")
                        st.rerun()

                history = query_df("""
                    SELECT old_stage AS önceki, new_stage AS yeni,
                           changed_at AS tarih, owner AS sorumlu, note AS notlar
                    FROM opportunity_stage_history
                    WHERE opportunity_id=?
                    ORDER BY id DESC
                """, (int(opp_id),))
                if not history.empty:
                    st.markdown("##### Aşama geçmişi")
                    st.dataframe(history, use_container_width=True, hide_index=True)

        with ptab2:
            customers = query_df("SELECT id, name FROM customers ORDER BY name")
            if customers.empty:
                st.info("Önce CRM'e müşteri ekleyin.")
            else:
                with st.form("ct_opp_form", clear_on_submit=True):
                    selected_name = st.selectbox("Müşteri", customers["name"].tolist())
                    product = st.text_input("Ürün *", key="ct_opp_product")
                    stage = st.selectbox("Aşama", STAGES)
                    o1, o2, o3 = st.columns(3)
                    value = o1.number_input("Fırsat değeri", min_value=0.0, step=1000.0)
                    currency = o2.selectbox("Para", ["EUR", "USD", "GBP", "TRY"])
                    probability = o3.number_input(
                        "Olasılık %", 0, 100, STAGE_PROBABILITY[stage]
                    )
                    next_action = st.text_input("Sonraki aksiyon", key="ct_opp_action")
                    o4, o5 = st.columns(2)
                    due = o4.date_input(
                        "Takip tarihi", value=date.today() + timedelta(days=3)
                    )
                    expected_close = o5.date_input(
                        "Tahmini kapanış", value=date.today() + timedelta(days=30)
                    )
                    owner = st.text_input("Sorumlu", key="ct_opp_owner")
                    notes = st.text_area("Not", key="ct_opp_notes")
                    if st.form_submit_button("Fırsatı kaydet", type="primary") and product.strip():
                        customer_id = int(
                            customers.loc[customers["name"] == selected_name, "id"].iloc[0]
                        )
                        execute(
                            """INSERT INTO opportunities
                            (customer_id,product,stage,value,currency,probability,
                             next_action,due_date,owner,notes,expected_close_date,updated_at)
                            VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
                            (
                                customer_id, product.strip(), stage, value, currency,
                                int(probability), next_action, str(due), owner, notes,
                                str(expected_close), datetime.now().isoformat(timespec="seconds")
                            )
                        )
                        new_opp_id = int(query_df(
                            "SELECT id FROM opportunities ORDER BY id DESC LIMIT 1"
                        ).iloc[0]["id"])
                        execute(
                            """INSERT INTO opportunity_stage_history
                            (opportunity_id,old_stage,new_stage,owner,note)
                            VALUES (?,?,?,?,?)""",
                            (new_opp_id, "", stage, owner, "Fırsat oluşturuldu")
                        )
                        st.success("Fırsat eklendi.")
                        st.rerun()

    with followup_tab:
        st.markdown("#### Geciken ve bugünkü takipler")
        followups = query_df("""
            SELECT o.id, c.name AS müşteri, o.product AS ürün, o.stage AS aşama,
                   o.next_action AS aksiyon, o.due_date AS takip_tarihi,
                   o.last_contact_date AS son_görüşme, o.owner AS sorumlu,
                   CAST(julianday(?) - julianday(NULLIF(o.due_date,'')) AS INTEGER) AS gecikme_gün
            FROM opportunities o
            LEFT JOIN customers c ON c.id=o.customer_id
            WHERE o.stage NOT IN ('Kazanıldı','Kaybedildi')
              AND o.due_date != '' AND o.due_date <= ?
            ORDER BY o.due_date ASC
        """, (str(date.today()), str(date.today())))
        st.dataframe(followups, use_container_width=True, hide_index=True)

        st.markdown("#### 14+ gündür temas edilmeyen aktif fırsatlar")
        stale = query_df("""
            SELECT o.id, c.name AS müşteri, o.product AS ürün, o.stage AS aşama,
                   o.value AS değer, o.currency AS para,
                   o.last_contact_date AS son_görüşme, o.next_action AS aksiyon,
                   o.owner AS sorumlu
            FROM opportunities o
            LEFT JOIN customers c ON c.id=o.customer_id
            WHERE o.stage NOT IN ('Kazanıldı','Kaybedildi')
              AND (
                   o.last_contact_date = ''
                   OR julianday(?) - julianday(o.last_contact_date) >= 14
              )
            ORDER BY o.value DESC
        """, (str(date.today()),))
        st.dataframe(stale, use_container_width=True, hide_index=True)

        st.markdown("#### Son satış aktiviteleri")
        recent = query_df("""
            SELECT a.activity_date AS tarih, c.name AS müşteri,
                   a.activity_type AS tip, a.summary AS notlar,
                   a.next_action AS sonraki_aksiyon,
                   a.next_action_date AS takip_tarihi, a.owner AS sorumlu
            FROM activities a
            LEFT JOIN customers c ON c.id=a.customer_id
            ORDER BY a.activity_date DESC, a.id DESC
            LIMIT 30
        """)
        st.dataframe(recent, use_container_width=True, hide_index=True)

    with tasks_tab:
        task_df = query_df("""
            SELECT id, title AS görev, related_to AS ilgili, owner AS sorumlu,
                   priority AS öncelik, due_date AS son_tarih, status AS durum
            FROM tasks
            ORDER BY CASE priority
                WHEN 'Kritik' THEN 1 WHEN 'Yüksek' THEN 2
                WHEN 'Orta' THEN 3 ELSE 4 END,
                due_date ASC
        """)
        st.dataframe(task_df, use_container_width=True, hide_index=True)

        with st.expander("Yeni görev ekle"):
            with st.form("ct_task_form", clear_on_submit=True):
                title = st.text_input("Görev *", key="ct_task_title")
                related = st.text_input("İlgili müşteri / ürün", key="ct_task_related")
                owner = st.text_input("Sorumlu", key="ct_task_owner")
                t1, t2 = st.columns(2)
                priority = t1.selectbox("Öncelik", ["Kritik", "Yüksek", "Orta", "Düşük"])
                due = t2.date_input("Son tarih", value=date.today() + timedelta(days=1))
                notes = st.text_area("Not", key="ct_task_notes")
                if st.form_submit_button("Görev ekle", type="primary") and title.strip():
                    execute(
                        """INSERT INTO tasks
                        (title,related_to,owner,priority,due_date,status,notes)
                        VALUES (?,?,?,?,?,'Açık',?)""",
                        (title.strip(), related, owner, priority, str(due), notes)
                    )
                    st.success("Görev eklendi.")
                    st.rerun()

        if not task_df.empty:
            st.markdown("#### Görev durumunu değiştir")
            task_id = st.selectbox(
                "Görev",
                task_df["id"].tolist(),
                format_func=lambda x: task_df.loc[task_df["id"] == x, "görev"].iloc[0],
                key="ct_task_close"
            )
            new_status = st.selectbox(
                "Yeni durum", ["Açık", "Devam", "Bekliyor", "Tamamlandı"],
                key="ct_task_new_status"
            )
            if st.button("Görevi güncelle"):
                execute("UPDATE tasks SET status=? WHERE id=?", (new_status, int(task_id)))
                st.success("Görev güncellendi.")
                st.rerun()

    with ceo_tab:
        opp = query_df(
            "SELECT value, probability FROM opportunities WHERE stage NOT IN ('Kaybedildi')"
        )
        weighted = float((opp["value"] * opp["probability"] / 100).sum()) if not opp.empty else 0
        risk = float(query_df(
            "SELECT COALESCE(SUM(value),0) v FROM opportunities WHERE stage='Problem / Koruma'"
        ).iloc[0]["v"])
        critical = int(query_df(
            """SELECT COUNT(*) n FROM tasks
               WHERE status != 'Tamamlandı' AND priority IN ('Kritik','Yüksek')"""
        ).iloc[0]["n"])
        overdue = int(query_df(
            """SELECT COUNT(*) n FROM opportunities
               WHERE stage NOT IN ('Kazanıldı','Kaybedildi')
                 AND due_date != '' AND due_date < ?""",
            (str(date.today()),)
        ).iloc[0]["n"])
        stale_count = int(query_df(
            """SELECT COUNT(*) n FROM opportunities
               WHERE stage NOT IN ('Kazanıldı','Kaybedildi')
                 AND (last_contact_date='' OR julianday(?) - julianday(last_contact_date) >= 14)""",
            (str(date.today()),)
        ).iloc[0]["n"])

        c1, c2, c3, c4, c5 = st.columns(5)
        c1.metric("Ağırlıklı fırsat", money(weighted))
        c2.metric("Risk altındaki iş", money(risk))
        c3.metric("Kritik / yüksek konu", critical)
        c4.metric("Geciken satış takibi", overdue)
        c5.metric("14+ gün sessiz fırsat", stale_count)

        st.markdown("#### Senden karar bekleyenler")
        decisions = query_df("""
            SELECT title AS konu, related_to AS ilgili, owner AS sorumlu,
                   priority AS öncelik, due_date AS tarih
            FROM tasks
            WHERE status != 'Tamamlandı'
              AND priority IN ('Kritik','Yüksek')
            ORDER BY CASE priority WHEN 'Kritik' THEN 1 ELSE 2 END, due_date ASC
            LIMIT 10
        """)
        st.dataframe(decisions, use_container_width=True, hide_index=True)

        st.markdown("#### En büyük aktif satış fırsatları")
        top = query_df("""
            SELECT c.name AS müşteri, o.product AS ürün, o.stage AS aşama,
                   o.value AS değer, o.currency AS para,
                   o.probability AS olasılık, o.next_action AS sonraki_aksiyon,
                   o.due_date AS takip_tarihi, o.owner AS sorumlu
            FROM opportunities o
            LEFT JOIN customers c ON c.id=o.customer_id
            WHERE o.stage NOT IN ('Kazanıldı','Kaybedildi')
            ORDER BY o.value DESC
            LIMIT 10
        """)
        st.dataframe(top, use_container_width=True, hide_index=True)

        st.markdown("#### Yönetici uyarısı")
        if overdue or stale_count or critical:
            st.warning(
                f"{critical} kritik/yüksek görev, {overdue} geciken satış takibi ve "
                f"{stale_count} uzun süredir temas edilmeyen aktif fırsat var."
            )
        else:
            st.success("Şu anda kritik gecikmiş satış takibi görünmüyor.")
