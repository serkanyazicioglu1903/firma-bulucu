import sqlite3
from datetime import date, datetime, timedelta
from pathlib import Path

import pandas as pd
import streamlit as st

DB_PATH = Path(__file__).with_name("as_control_tower.db")


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
        """)
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
        (customer_id,product,stage,value,currency,probability,next_action,due_date,owner,notes)
        VALUES (?,?,?,?,?,?,?,?,?,?)""",
        (c1, "Pantur 1250", "Problem / Koruma", 350000, "EUR", 70,
         "Tedarikçi teknik/ticari çözümünü netleştir", str(date.today() + timedelta(days=2)),
         "Serkan", "Müşteri kaybı ve claim riski.")
    )
    execute(
        """INSERT INTO opportunities
        (customer_id,product,stage,value,currency,probability,next_action,due_date,owner,notes)
        VALUES (?,?,?,?,?,?,?,?,?,?)""",
        (c2, "Mokaero 22 Topping Base", "Deneme", 120000, "EUR", 55,
         "Endüstriyel deneme sonucunu takip et", str(date.today() + timedelta(days=3)),
         "Satış", "")
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
        exists = int(query_df("SELECT COUNT(*) n FROM customers WHERE lower(name)=lower(?)", (name,)).iloc[0]["n"])
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
        exists = int(query_df("SELECT COUNT(*) n FROM customers WHERE lower(name)=lower(?)", (name,)).iloc[0]["n"])
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


def render_control_tower():
    init_db()
    seed_once()

    st.subheader("🧭 AS CONTROL TOWER")
    st.caption("Satış • müşteri • fırsat • görev • karar merkezi")

    dashboard, customers_tab, opportunities_tab, tasks_tab, ceo_tab = st.tabs(
        ["📊 Yönetici Paneli", "👥 CRM", "💰 Fırsatlar", "✅ Görevler", "🎯 Serkan Ekranı"]
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
        open_tasks = int(query_df("SELECT COUNT(*) n FROM tasks WHERE status != 'Tamamlandı'").iloc[0]["n"])

        m1, m2, m3, m4 = st.columns(4)
        m1.metric("CRM kayıtları", customer_count)
        m2.metric("Aktif fırsat", active_opps)
        m3.metric("Ağırlıklı fırsat", money(weighted))
        m4.metric("Açık görev", open_tasks)

        st.markdown("#### Bugün müdahale gerektirenler")
        urgent = query_df("""
            SELECT title AS görev, related_to AS ilgili, owner AS sorumlu,
                   priority AS öncelik, due_date AS tarih, status AS durum
            FROM tasks
            WHERE status != 'Tamamlandı'
            ORDER BY CASE priority
                WHEN 'Kritik' THEN 1 WHEN 'Yüksek' THEN 2
                WHEN 'Orta' THEN 3 ELSE 4 END,
                due_date ASC
            LIMIT 10
        """)
        st.dataframe(urgent, use_container_width=True, hide_index=True)

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
        st.markdown("#### Müşteri / şirket kartları")
        customer_df = query_df("""
            SELECT id, name AS firma, country AS ülke, sector AS sektör,
                   status AS durum, owner AS sorumlu,
                   annual_potential AS yıllık_potansiyel,
                   currency AS para, contact_name AS kişi,
                   contact_email AS email, phone AS telefon, source AS kaynak
            FROM customers ORDER BY id DESC
        """)
        st.dataframe(customer_df, use_container_width=True, hide_index=True)

        with st.expander("Yeni müşteri / şirket ekle"):
            with st.form("ct_customer_form", clear_on_submit=True):
                name = st.text_input("Firma adı *", key="ct_customer_name")
                c1, c2 = st.columns(2)
                country = c1.text_input("Ülke", key="ct_customer_country")
                sector = c2.text_input("Sektör", key="ct_customer_sector")
                c3, c4 = st.columns(2)
                status = c3.selectbox("Durum", ["Potansiyel", "Aktif", "Riskli", "Pasif", "Satın Alma Adayı"])
                owner = c4.text_input("Sorumlu", key="ct_customer_owner")
                contact = st.text_input("Kontak kişi", key="ct_customer_contact")
                email = st.text_input("E-posta", key="ct_customer_email")
                phone = st.text_input("Telefon", key="ct_customer_phone")
                notes = st.text_area("Not", key="ct_customer_notes")
                if st.form_submit_button("Kaydet", type="primary") and name.strip():
                    execute(
                        """INSERT INTO customers
                        (name,country,sector,status,owner,contact_name,contact_email,phone,source,notes)
                        VALUES (?,?,?,?,?,?,?,?,?,?)""",
                        (name.strip(), country, sector, status, owner, contact, email, phone, "Manuel", notes)
                    )
                    st.success("CRM kaydı eklendi.")

    with opportunities_tab:
        pipeline = query_df("""
            SELECT o.id, c.name AS müşteri, o.product AS ürün, o.stage AS aşama,
                   o.value AS değer, o.currency AS para, o.probability AS olasılık,
                   o.next_action AS sonraki_aksiyon, o.due_date AS tarih, o.owner AS sorumlu
            FROM opportunities o
            LEFT JOIN customers c ON c.id=o.customer_id
            ORDER BY o.value DESC
        """)
        st.dataframe(pipeline, use_container_width=True, hide_index=True)

        with st.expander("Yeni satış fırsatı ekle"):
            customers = query_df("SELECT id, name FROM customers ORDER BY name")
            if customers.empty:
                st.info("Önce CRM'e müşteri ekleyin.")
            else:
                with st.form("ct_opp_form", clear_on_submit=True):
                    selected_name = st.selectbox("Müşteri", customers["name"].tolist())
                    product = st.text_input("Ürün *", key="ct_opp_product")
                    stage = st.selectbox(
                        "Aşama",
                        ["Lead", "Temas", "Numune", "Deneme", "Teklif", "Pazarlık",
                         "Sipariş", "Kazanıldı", "Kaybedildi", "Problem / Koruma"]
                    )
                    o1, o2, o3 = st.columns(3)
                    value = o1.number_input("Fırsat değeri", min_value=0.0, step=1000.0)
                    currency = o2.selectbox("Para", ["EUR", "USD", "GBP", "TRY"])
                    probability = o3.number_input("Olasılık %", 0, 100, 25)
                    next_action = st.text_input("Sonraki aksiyon", key="ct_opp_action")
                    due = st.date_input("Takip tarihi", value=date.today() + timedelta(days=7))
                    owner = st.text_input("Sorumlu", key="ct_opp_owner")
                    if st.form_submit_button("Fırsatı kaydet", type="primary") and product.strip():
                        customer_id = int(
                            customers.loc[customers["name"] == selected_name, "id"].iloc[0]
                        )
                        execute(
                            """INSERT INTO opportunities
                            (customer_id,product,stage,value,currency,probability,next_action,due_date,owner)
                            VALUES (?,?,?,?,?,?,?,?,?)""",
                            (customer_id, product.strip(), stage, value, currency, probability,
                             next_action, str(due), owner)
                        )
                        st.success("Fırsat eklendi.")

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

        if not task_df.empty:
            st.markdown("#### Görev kapat")
            task_id = st.selectbox(
                "Görev",
                task_df["id"].tolist(),
                format_func=lambda x: task_df.loc[task_df["id"] == x, "görev"].iloc[0],
                key="ct_task_close"
            )
            if st.button("Tamamlandı olarak işaretle"):
                execute("UPDATE tasks SET status='Tamamlandı' WHERE id=?", (int(task_id),))
                st.success("Görev tamamlandı.")
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
            """SELECT COUNT(*) n FROM tasks
               WHERE status != 'Tamamlandı' AND due_date != '' AND due_date < ?""",
            (str(date.today()),)
        ).iloc[0]["n"])

        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Ağırlıklı fırsat", money(weighted))
        c2.metric("Risk altındaki iş", money(risk))
        c3.metric("Kritik / yüksek konu", critical)
        c4.metric("Gecikmiş görev", overdue)

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

        st.markdown("#### En büyük aktif fırsatlar")
        top = query_df("""
            SELECT c.name AS müşteri, o.product AS ürün, o.stage AS aşama,
                   o.value AS değer, o.currency AS para,
                   o.probability AS olasılık, o.next_action AS sonraki_aksiyon
            FROM opportunities o
            LEFT JOIN customers c ON c.id=o.customer_id
            WHERE o.stage NOT IN ('Kazanıldı','Kaybedildi')
            ORDER BY o.value DESC
            LIMIT 10
        """)
        st.dataframe(top, use_container_width=True, hide_index=True)
