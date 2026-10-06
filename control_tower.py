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

        CREATE TABLE IF NOT EXISTS product_catalog (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL UNIQUE,
            category TEXT DEFAULT '',
            supplier TEXT DEFAULT '',
            supplier_country TEXT DEFAULT '',
            target_sectors TEXT DEFAULT '',
            applications TEXT DEFAULT '',
            default_currency TEXT DEFAULT 'EUR',
            default_opportunity_value REAL DEFAULT 100000,
            active INTEGER DEFAULT 1,
            notes TEXT DEFAULT '',
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS customer_product_status (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            customer_id INTEGER NOT NULL,
            product_id INTEGER NOT NULL,
            status TEXT DEFAULT 'Potansiyel',
            current_supplier TEXT DEFAULT '',
            annual_volume_tons REAL DEFAULT 0,
            notes TEXT DEFAULT '',
            updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(customer_id, product_id),
            FOREIGN KEY(customer_id) REFERENCES customers(id),
            FOREIGN KEY(product_id) REFERENCES product_catalog(id)
        );

        CREATE TABLE IF NOT EXISTS quotes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            customer_id INTEGER,
            opportunity_id INTEGER,
            product_name TEXT NOT NULL,
            quantity_kg REAL DEFAULT 0,
            base_currency TEXT DEFAULT 'EUR',
            buy_price_per_kg REAL DEFAULT 0,
            buy_currency TEXT DEFAULT 'EUR',
            buy_fx_to_base REAL DEFAULT 1,
            freight_total_base REAL DEFAULT 0,
            customs_rate_pct REAL DEFAULT 0,
            customs_fixed_base REAL DEFAULT 0,
            import_other_total_base REAL DEFAULT 0,
            handling_total_base REAL DEFAULT 0,
            finance_rate_pct REAL DEFAULT 0,
            prepayment_days INTEGER DEFAULT 0,
            stock_days INTEGER DEFAULT 0,
            customer_credit_days INTEGER DEFAULT 0,
            sell_price_per_kg REAL DEFAULT 0,
            sell_currency TEXT DEFAULT 'EUR',
            sell_fx_to_base REAL DEFAULT 1,
            sales_commission_pct REAL DEFAULT 0,
            target_margin_pct REAL DEFAULT 0,
            incoterm TEXT DEFAULT '',
            valid_until TEXT DEFAULT '',
            status TEXT DEFAULT 'Taslak',
            notes TEXT DEFAULT '',
            landed_cost_per_kg REAL DEFAULT 0,
            finance_cost_per_kg REAL DEFAULT 0,
            total_cost_per_kg REAL DEFAULT 0,
            profit_per_kg REAL DEFAULT 0,
            profit_total_base REAL DEFAULT 0,
            margin_pct REAL DEFAULT 0,
            required_sell_price REAL DEFAULT 0,
            finance_days INTEGER DEFAULT 0,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(customer_id) REFERENCES customers(id),
            FOREIGN KEY(opportunity_id) REFERENCES opportunities(id)
        );

        CREATE TABLE IF NOT EXISTS warehouses (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL UNIQUE,
            warehouse_type TEXT DEFAULT 'Normal Depo',
            city TEXT DEFAULT '',
            active INTEGER DEFAULT 1,
            notes TEXT DEFAULT '',
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS purchase_orders (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            po_number TEXT NOT NULL UNIQUE,
            supplier TEXT NOT NULL,
            product_id INTEGER,
            product_name TEXT NOT NULL,
            quantity_kg REAL DEFAULT 0,
            unit_price REAL DEFAULT 0,
            currency TEXT DEFAULT 'EUR',
            incoterm TEXT DEFAULT '',
            payment_terms TEXT DEFAULT '',
            order_date TEXT DEFAULT '',
            requested_load_date TEXT DEFAULT '',
            confirmed_load_date TEXT DEFAULT '',
            destination_warehouse_id INTEGER,
            status TEXT DEFAULT 'Sipariş Verildi',
            notes TEXT DEFAULT '',
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(product_id) REFERENCES product_catalog(id),
            FOREIGN KEY(destination_warehouse_id) REFERENCES warehouses(id)
        );

        CREATE TABLE IF NOT EXISTS shipments (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            purchase_order_id INTEGER NOT NULL,
            shipment_ref TEXT DEFAULT '',
            quantity_kg REAL DEFAULT 0,
            transport_mode TEXT DEFAULT 'Tır',
            carrier TEXT DEFAULT '',
            container_vehicle TEXT DEFAULT '',
            etd TEXT DEFAULT '',
            eta TEXT DEFAULT '',
            customs_date TEXT DEFAULT '',
            delivery_date TEXT DEFAULT '',
            status TEXT DEFAULT 'Planlandı',
            destination_warehouse_id INTEGER,
            lot_number TEXT DEFAULT '',
            expiry_date TEXT DEFAULT '',
            received_to_stock INTEGER DEFAULT 0,
            notes TEXT DEFAULT '',
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(purchase_order_id) REFERENCES purchase_orders(id),
            FOREIGN KEY(destination_warehouse_id) REFERENCES warehouses(id)
        );

        CREATE TABLE IF NOT EXISTS inventory_lots (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            product_id INTEGER,
            product_name TEXT NOT NULL,
            warehouse_id INTEGER NOT NULL,
            lot_number TEXT DEFAULT '',
            expiry_date TEXT DEFAULT '',
            quantity_received_kg REAL DEFAULT 0,
            quantity_available_kg REAL DEFAULT 0,
            quantity_reserved_kg REAL DEFAULT 0,
            unit_cost REAL DEFAULT 0,
            currency TEXT DEFAULT 'EUR',
            purchase_order_id INTEGER,
            shipment_id INTEGER,
            received_date TEXT DEFAULT '',
            notes TEXT DEFAULT '',
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(product_id) REFERENCES product_catalog(id),
            FOREIGN KEY(warehouse_id) REFERENCES warehouses(id),
            FOREIGN KEY(purchase_order_id) REFERENCES purchase_orders(id),
            FOREIGN KEY(shipment_id) REFERENCES shipments(id)
        );

        CREATE TABLE IF NOT EXISTS inventory_policy (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            product_id INTEGER NOT NULL UNIQUE,
            monthly_usage_kg REAL DEFAULT 0,
            safety_stock_days INTEGER DEFAULT 30,
            lead_time_days INTEGER DEFAULT 45,
            reorder_review_days INTEGER DEFAULT 7,
            notes TEXT DEFAULT '',
            updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(product_id) REFERENCES product_catalog(id)
        );

        CREATE TABLE IF NOT EXISTS cash_accounts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL UNIQUE,
            currency TEXT DEFAULT 'EUR',
            balance REAL DEFAULT 0,
            fx_to_base REAL DEFAULT 1,
            base_currency TEXT DEFAULT 'EUR',
            account_type TEXT DEFAULT 'Banka',
            active INTEGER DEFAULT 1,
            notes TEXT DEFAULT '',
            updated_at TEXT DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS receivables (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            customer_id INTEGER NOT NULL,
            invoice_no TEXT DEFAULT '',
            invoice_date TEXT DEFAULT '',
            due_date TEXT NOT NULL,
            amount REAL DEFAULT 0,
            paid_amount REAL DEFAULT 0,
            currency TEXT DEFAULT 'EUR',
            fx_to_base REAL DEFAULT 1,
            base_currency TEXT DEFAULT 'EUR',
            status TEXT DEFAULT 'Açık',
            opportunity_id INTEGER,
            notes TEXT DEFAULT '',
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(customer_id) REFERENCES customers(id),
            FOREIGN KEY(opportunity_id) REFERENCES opportunities(id)
        );

        CREATE TABLE IF NOT EXISTS payables (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            supplier TEXT NOT NULL,
            purchase_order_id INTEGER,
            invoice_no TEXT DEFAULT '',
            invoice_date TEXT DEFAULT '',
            due_date TEXT NOT NULL,
            amount REAL DEFAULT 0,
            paid_amount REAL DEFAULT 0,
            currency TEXT DEFAULT 'EUR',
            fx_to_base REAL DEFAULT 1,
            base_currency TEXT DEFAULT 'EUR',
            status TEXT DEFAULT 'Açık',
            notes TEXT DEFAULT '',
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(purchase_order_id) REFERENCES purchase_orders(id)
        );

        CREATE TABLE IF NOT EXISTS finance_transactions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            transaction_type TEXT NOT NULL,
            receivable_id INTEGER,
            payable_id INTEGER,
            transaction_date TEXT NOT NULL,
            amount REAL DEFAULT 0,
            currency TEXT DEFAULT 'EUR',
            fx_to_base REAL DEFAULT 1,
            base_currency TEXT DEFAULT 'EUR',
            account_id INTEGER,
            reference TEXT DEFAULT '',
            notes TEXT DEFAULT '',
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(receivable_id) REFERENCES receivables(id),
            FOREIGN KEY(payable_id) REFERENCES payables(id),
            FOREIGN KEY(account_id) REFERENCES cash_accounts(id)
        );

        CREATE TABLE IF NOT EXISTS cash_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            event_date TEXT NOT NULL,
            direction TEXT NOT NULL,
            category TEXT DEFAULT 'Diğer',
            description TEXT NOT NULL,
            amount REAL DEFAULT 0,
            currency TEXT DEFAULT 'EUR',
            fx_to_base REAL DEFAULT 1,
            base_currency TEXT DEFAULT 'EUR',
            status TEXT DEFAULT 'Planlı',
            notes TEXT DEFAULT '',
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        );
        """)

        ensure_column(conn, "opportunities", "last_contact_date", "TEXT DEFAULT ''")
        ensure_column(conn, "opportunities", "expected_close_date", "TEXT DEFAULT ''")
        ensure_column(conn, "opportunities", "lost_reason", "TEXT DEFAULT ''")
        ensure_column(conn, "opportunities", "updated_at", "TEXT DEFAULT ''")
        ensure_column(conn, "customers", "product_profile", "TEXT DEFAULT ''")
        ensure_column(conn, "customers", "priority_tier", "TEXT DEFAULT 'B'")
        ensure_column(conn, "customers", "credit_limit", "REAL DEFAULT 0")
        ensure_column(conn, "customers", "default_payment_days", "INTEGER DEFAULT 90")
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


def seed_product_catalog():
    products = [
        (
            "Pantur 1250",
            "Release Agent / Tava Yağı",
            "Sonneveld",
            "Hollanda",
            "bisküvi;fırıncılık;bakery;bread;cake;wafer;unlu mamul",
            "Tava ve kalıp ayırıcı; endüstriyel fırıncılık",
            180000,
        ),
        (
            "Mokaero 22 Topping Base",
            "Topping Base",
            "Mokate",
            "Polonya",
            "fırıncılık;bakery;pasta;cake;pastacılık;confectionery;şekerleme",
            "Topping, whipping ve pastacılık uygulamaları",
            120000,
        ),
        (
            "Fat Powder FI FP 80 PR 01",
            "Fat Powder",
            "Mokate",
            "Polonya",
            "çikolata;confectionery;şekerleme;fırıncılık;bakery;süt;dairy;toz içecek;beverage",
            "Yağ tozu; dolgu, içecek ve kuru karışım uygulamaları",
            250000,
        ),
        (
            "Methocel MCE-100 TS / NE-4000",
            "Cellulose / Hydrocolloid",
            "SE Tylose",
            "Almanya",
            "et;meat;vegan;plant based;sos;sauce;fırıncılık;bakery;hazır gıda",
            "Bağlama, tekstür, stabilizasyon ve su tutma",
            150000,
        ),
        (
            "Oat Fibre",
            "Fibre",
            "Grainmore",
            "Avrupa",
            "et;meat;fırıncılık;bakery;vegan;plant based;snack;sağlıklı gıda",
            "Lif zenginleştirme, su tutma ve tekstür",
            100000,
        ),
        (
            "Egg White Powder",
            "Egg Products",
            "Naturovos",
            "Avrupa",
            "fırıncılık;bakery;cake;pasta;confectionery;şekerleme;protein;hazır gıda",
            "Köpürme, bağlama, protein ve pastacılık",
            220000,
        ),
        (
            "Vital Wheat Gluten",
            "Wheat Protein",
            "Fidelinka",
            "Avrupa",
            "fırıncılık;bakery;bread;ekmek;unlu mamul;vegan;plant based;meat",
            "Hamur güçlendirme ve protein",
            300000,
        ),
        (
            "GMS Food Grade",
            "Emulsifier",
            "Solvay",
            "Hollanda",
            "fırıncılık;bakery;cake;dairy;süt;ice cream;dondurma;confectionery;şekerleme",
            "Emülsifikasyon, yapı ve stabilizasyon",
            180000,
        ),
        (
            "Cocoa Mass",
            "Cocoa",
            "",
            "",
            "çikolata;chocolate;confectionery;şekerleme;bisküvi;bakery;ice cream;dondurma",
            "Çikolata, kaplama, dolgu ve kakao bazlı uygulamalar",
            400000,
        ),
        (
            "Deodorized Cocoa Butter",
            "Cocoa",
            "",
            "",
            "çikolata;chocolate;confectionery;şekerleme;bisküvi;bakery;ice cream;dondurma",
            "Çikolata, kaplama ve yağ fazı uygulamaları",
            400000,
        ),
        (
            "Dextrose Monohydrate",
            "Sweetener / Carbohydrate",
            "",
            "",
            "şekerleme;confectionery;beverage;içecek;bakery;fırıncılık;meat;et;dairy;süt;ice cream",
            "Tatlandırma, fermentasyon, tekstür ve kuru karışımlar",
            250000,
        ),
    ]

    for name, category, supplier, supplier_country, target_sectors, applications, default_value in products:
        exists = int(query_df(
            "SELECT COUNT(*) n FROM product_catalog WHERE lower(name)=lower(?)",
            (name,)
        ).iloc[0]["n"])
        if exists:
            continue
        execute(
            """INSERT INTO product_catalog
            (name,category,supplier,supplier_country,target_sectors,applications,
             default_currency,default_opportunity_value,active)
            VALUES (?,?,?,?,?,?, 'EUR', ?, 1)""",
            (
                name, category, supplier, supplier_country,
                target_sectors, applications, float(default_value)
            )
        )


def normalized_text(value):
    return str(value or "").lower().replace("ı", "i").replace("İ", "i")


def recommendation_rows(customer_id=None, product_id=None):
    customers = query_df("""
        SELECT id,name,country,sector,status,owner,annual_potential,currency,
               notes,product_profile,priority_tier,source
        FROM customers
        WHERE COALESCE(status,'') != 'Satın Alma Adayı'
          AND COALESCE(source,'') != 'Üretici Bulucu'
    """)
    products = query_df("""
        SELECT id,name,category,supplier,target_sectors,applications,
               default_currency,default_opportunity_value
        FROM product_catalog
        WHERE active=1
    """)

    if customer_id is not None:
        customers = customers[customers["id"] == int(customer_id)]
    if product_id is not None:
        products = products[products["id"] == int(product_id)]

    existing = query_df("""
        SELECT customer_id, lower(product) AS product_key, stage
        FROM opportunities
        WHERE stage != 'Kaybedildi'
    """)
    existing_keys = {
        (int(r["customer_id"]), normalized_text(r["product_key"]))
        for _, r in existing.iterrows()
    }

    status_df = query_df("""
        SELECT customer_id, product_id, status, current_supplier, annual_volume_tons, notes
        FROM customer_product_status
    """)
    status_map = {
        (int(r["customer_id"]), int(r["product_id"])): r
        for _, r in status_df.iterrows()
    }

    rows = []
    for _, c in customers.iterrows():
        customer_text = normalized_text(
            f"{c['sector']} {c['notes']} {c['product_profile']}"
        )
        if not customer_text.strip():
            continue

        for _, p in products.iterrows():
            if (int(c["id"]), normalized_text(p["name"])) in existing_keys:
                continue

            status_row = status_map.get((int(c["id"]), int(p["id"])))
            known_status = str(status_row["status"]) if status_row is not None else ""
            if known_status in {"Mevcut", "Uygun Değil"}:
                continue

            keywords = [
                normalized_text(x).strip()
                for x in str(p["target_sectors"] or "").split(";")
                if str(x).strip()
            ]
            matched = [k for k in keywords if k and k in customer_text]
            if not matched:
                continue

            score = min(70, 35 + 12 * len(set(matched)))
            reasons = [f"Sektör eşleşmesi: {', '.join(list(dict.fromkeys(matched))[:4])}"]

            if str(c["status"]) == "Aktif":
                score += 10
                reasons.append("aktif müşteri")
            tier = str(c["priority_tier"] or "B").upper()
            if tier == "A":
                score += 10
                reasons.append("A öncelik")
            elif tier == "B":
                score += 5

            potential = float(c["annual_potential"] or 0)
            if potential >= 500000:
                score += 10
                reasons.append("yüksek müşteri potansiyeli")
            elif potential >= 100000:
                score += 5

            if known_status == "Rakipte":
                score += 15
                reasons.append("ürün rakip tedarikçide")
            elif known_status == "Potansiyel":
                score += 5

            score = min(100, int(score))
            rows.append({
                "customer_id": int(c["id"]),
                "product_id": int(p["id"]),
                "Müşteri": c["name"],
                "Ürün": p["name"],
                "Kategori": p["category"],
                "Tedarikçi": p["supplier"],
                "Fit Score": score,
                "Neden": "; ".join(reasons),
                "Durum": known_status or "Yeni öneri",
                "Sorumlu": c["owner"],
                "Önerilen Fırsat Değeri": float(p["default_opportunity_value"] or 0),
                "Para": p["default_currency"] or "EUR",
                "Uygulama": p["applications"],
            })

    if not rows:
        return pd.DataFrame()
    return pd.DataFrame(rows).sort_values(
        ["Fit Score", "Önerilen Fırsat Değeri"], ascending=[False, False]
    ).reset_index(drop=True)


def create_opportunity_from_recommendation(customer_id, product_id, value, owner):
    product = query_df(
        "SELECT * FROM product_catalog WHERE id=?", (int(product_id),)
    )
    customer = query_df(
        "SELECT * FROM customers WHERE id=?", (int(customer_id),)
    )
    if product.empty or customer.empty:
        return False, "Müşteri veya ürün bulunamadı."

    product_row = product.iloc[0]
    customer_row = customer.iloc[0]
    duplicate = int(query_df(
        """SELECT COUNT(*) n FROM opportunities
           WHERE customer_id=? AND lower(product)=lower(?)
             AND stage != 'Kaybedildi'""",
        (int(customer_id), product_row["name"])
    ).iloc[0]["n"])
    if duplicate:
        return False, "Bu müşteri ve ürün için zaten açık/kazanılmış fırsat var."

    due = date.today() + timedelta(days=3)
    close = date.today() + timedelta(days=45)
    execute(
        """INSERT INTO opportunities
        (customer_id,product,stage,value,currency,probability,next_action,
         due_date,owner,notes,expected_close_date,updated_at)
        VALUES (?,?, 'Lead', ?, ?, 10, ?, ?, ?, ?, ?, ?)""",
        (
            int(customer_id),
            product_row["name"],
            float(value),
            product_row["default_currency"] or "EUR",
            f"{product_row['name']} için ilk temas / ihtiyaç doğrulaması",
            str(due),
            owner or customer_row["owner"] or "",
            "AS Control Tower Ürün × Müşteri motorundan oluşturuldu.",
            str(close),
            datetime.now().isoformat(timespec="seconds"),
        )
    )
    opp_id = int(query_df(
        "SELECT id FROM opportunities ORDER BY id DESC LIMIT 1"
    ).iloc[0]["id"])
    execute(
        """INSERT INTO opportunity_stage_history
        (opportunity_id,old_stage,new_stage,owner,note)
        VALUES (?, '', 'Lead', ?, ?)""",
        (
            opp_id,
            owner or customer_row["owner"] or "",
            "Ürün × Müşteri önerisinden fırsata çevrildi"
        )
    )
    execute(
        """INSERT INTO tasks
        (title,related_to,owner,priority,due_date,status,notes)
        VALUES (?,?,?,?,?,'Açık',?)""",
        (
            f"{product_row['name']} için ilk temas",
            customer_row["name"],
            owner or customer_row["owner"] or "",
            "Yüksek",
            str(due),
            f"Cross-sell fırsatı #{opp_id}"
        )
    )
    return True, f"Fırsat #{opp_id} oluşturuldu."


def save_customer_product_status(customer_id, product_id, status, current_supplier,
                                 annual_volume_tons, notes):
    execute(
        """INSERT INTO customer_product_status
        (customer_id,product_id,status,current_supplier,annual_volume_tons,notes,updated_at)
        VALUES (?,?,?,?,?,?,?)
        ON CONFLICT(customer_id,product_id) DO UPDATE SET
            status=excluded.status,
            current_supplier=excluded.current_supplier,
            annual_volume_tons=excluded.annual_volume_tons,
            notes=excluded.notes,
            updated_at=excluded.updated_at
        """,
        (
            int(customer_id), int(product_id), status, current_supplier,
            float(annual_volume_tons), notes,
            datetime.now().isoformat(timespec="seconds")
        )
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


def seed_warehouses():
    defaults = [
        ("Merkez Depo", "Normal Depo"),
        ("Antrepo", "Antrepo / Bonded"),
    ]
    for name, warehouse_type in defaults:
        exists = int(query_df(
            "SELECT COUNT(*) n FROM warehouses WHERE lower(name)=lower(?)",
            (name,)
        ).iloc[0]["n"])
        if not exists:
            execute(
                """INSERT INTO warehouses (name,warehouse_type,active,notes)
                   VALUES (?,?,1,?)""",
                (name, warehouse_type, "Sistem başlangıç kaydı; gerçek depo adıyla düzenlenebilir.")
            )


def stock_snapshot():
    products = query_df("""
        SELECT id,name,supplier
        FROM product_catalog
        WHERE active=1
        ORDER BY name
    """)
    if products.empty:
        return pd.DataFrame()

    lots = query_df("""
        SELECT product_id,
               SUM(quantity_available_kg) AS available_kg,
               SUM(quantity_reserved_kg) AS reserved_kg
        FROM inventory_lots
        GROUP BY product_id
    """)
    inbound = query_df("""
        SELECT po.product_id,
               SUM(CASE
                     WHEN s.received_to_stock=0
                      AND s.status!='İptal'
                     THEN s.quantity_kg ELSE 0 END) AS inbound_kg
        FROM shipments s
        JOIN purchase_orders po ON po.id=s.purchase_order_id
        GROUP BY po.product_id
    """)
    po_open = query_df("""
        SELECT product_id,
               SUM(CASE
                     WHEN status NOT IN ('Tamamlandı','İptal')
                     THEN quantity_kg ELSE 0 END) AS open_po_kg
        FROM purchase_orders
        GROUP BY product_id
    """)
    policies = query_df("""
        SELECT product_id,monthly_usage_kg,safety_stock_days,lead_time_days,reorder_review_days
        FROM inventory_policy
    """)

    df = products.copy()
    for src in (lots, inbound, po_open, policies):
        if not src.empty:
            df = df.merge(src, left_on="id", right_on="product_id", how="left")
            if "product_id" in df.columns:
                df = df.drop(columns=["product_id"])

    for col in ["available_kg","reserved_kg","inbound_kg","open_po_kg","monthly_usage_kg"]:
        if col not in df.columns:
            df[col] = 0.0
        df[col] = df[col].fillna(0.0)

    for col, default in [("safety_stock_days",30),("lead_time_days",45),("reorder_review_days",7)]:
        if col not in df.columns:
            df[col] = default
        df[col] = df[col].fillna(default)

    df["net_available_kg"] = (df["available_kg"] - df["reserved_kg"]).clip(lower=0)
    df["daily_usage_kg"] = df["monthly_usage_kg"] / 30.0
    df["stock_days"] = df.apply(
        lambda r: round(r["net_available_kg"] / r["daily_usage_kg"], 1)
        if r["daily_usage_kg"] > 0 else None,
        axis=1
    )
    df["projected_stock_kg"] = df["net_available_kg"] + df["inbound_kg"]
    df["reorder_point_kg"] = df["daily_usage_kg"] * (
        df["lead_time_days"] + df["safety_stock_days"] + df["reorder_review_days"]
    )
    df["suggested_order_kg"] = (
        df["reorder_point_kg"] - df["projected_stock_kg"]
    ).clip(lower=0)
    df["status"] = df.apply(
        lambda r:
            "TÜKENECEK / SİPARİŞ VER"
            if r["monthly_usage_kg"] > 0 and r["projected_stock_kg"] < r["reorder_point_kg"]
            else (
                "KRİTİK STOK"
                if r["monthly_usage_kg"] > 0 and r["stock_days"] is not None
                and r["stock_days"] < r["safety_stock_days"]
                else "OK"
            ),
        axis=1
    )
    return df


def receive_shipment_to_stock(shipment_id):
    shipment = query_df("""
        SELECT s.*, po.product_id, po.product_name, po.unit_price, po.currency,
               po.destination_warehouse_id AS po_warehouse_id
        FROM shipments s
        JOIN purchase_orders po ON po.id=s.purchase_order_id
        WHERE s.id=?
    """, (int(shipment_id),))
    if shipment.empty:
        return False, "Sevkiyat bulunamadı."

    row = shipment.iloc[0]
    if int(row["received_to_stock"] or 0) == 1:
        return False, "Bu sevkiyat daha önce stoğa alınmış."

    warehouse_id = row["destination_warehouse_id"] or row["po_warehouse_id"]
    if not warehouse_id:
        return False, "Depo seçilmeden stok girişi yapılamaz."

    received_date = row["delivery_date"] or str(date.today())
    execute(
        """INSERT INTO inventory_lots
        (product_id,product_name,warehouse_id,lot_number,expiry_date,
         quantity_received_kg,quantity_available_kg,quantity_reserved_kg,
         unit_cost,currency,purchase_order_id,shipment_id,received_date,notes)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (
            int(row["product_id"]) if row["product_id"] else None,
            row["product_name"],
            int(warehouse_id),
            row["lot_number"] or "",
            row["expiry_date"] or "",
            float(row["quantity_kg"] or 0),
            float(row["quantity_kg"] or 0),
            0.0,
            float(row["unit_price"] or 0),
            row["currency"] or "EUR",
            int(row["purchase_order_id"]),
            int(shipment_id),
            received_date,
            "Sevkiyattan otomatik stok girişi"
        )
    )
    execute(
        """UPDATE shipments
           SET received_to_stock=1,
               status='Teslim Edildi',
               delivery_date=CASE WHEN delivery_date='' THEN ? ELSE delivery_date END
           WHERE id=?""",
        (str(date.today()), int(shipment_id))
    )

    po_summary = query_df("""
        SELECT po.quantity_kg AS ordered_kg,
               COALESCE(SUM(CASE WHEN s.received_to_stock=1 THEN s.quantity_kg ELSE 0 END),0) AS received_kg
        FROM purchase_orders po
        LEFT JOIN shipments s ON s.purchase_order_id=po.id AND s.status!='İptal'
        WHERE po.id=?
        GROUP BY po.id,po.quantity_kg
    """, (int(row["purchase_order_id"]),))
    if not po_summary.empty:
        ordered_kg = float(po_summary.iloc[0]["ordered_kg"] or 0)
        received_kg = float(po_summary.iloc[0]["received_kg"] or 0)
        po_status = "Tamamlandı" if received_kg + 0.001 >= ordered_kg else "Kısmi Sevk"
        execute(
            "UPDATE purchase_orders SET status=? WHERE id=?",
            (po_status, int(row["purchase_order_id"]))
        )
    return True, "Sevkiyat stoğa alındı."


def outstanding_receivables():
    df = query_df("""
        SELECT r.id,r.customer_id,c.name AS customer,r.invoice_no,r.invoice_date,
               r.due_date,r.amount,r.paid_amount,
               CASE WHEN r.amount-r.paid_amount < 0 THEN 0 ELSE r.amount-r.paid_amount END AS outstanding,
               r.currency,r.fx_to_base,r.base_currency,r.status,r.opportunity_id,r.notes,
               c.credit_limit,c.default_payment_days
        FROM receivables r
        JOIN customers c ON c.id=r.customer_id
        WHERE (r.amount-r.paid_amount) > 0.0001
          AND r.status != 'İptal'
        ORDER BY r.due_date ASC,r.id ASC
    """)
    if df.empty:
        return df
    today = pd.Timestamp(date.today())
    due = pd.to_datetime(df["due_date"], errors="coerce")
    df["days_overdue"] = (today - due).dt.days.fillna(0).astype(int)
    df["days_overdue"] = df["days_overdue"].clip(lower=0)
    df["outstanding_base"] = df["outstanding"] * df["fx_to_base"].fillna(1)
    df["risk"] = df.apply(
        lambda r:
            "KRİTİK" if r["days_overdue"] >= 30
            else ("GECİKMİŞ" if r["days_overdue"] > 0 else "AÇIK"),
        axis=1
    )
    return df


def outstanding_payables():
    df = query_df("""
        SELECT p.id,p.supplier,p.purchase_order_id,p.invoice_no,p.invoice_date,
               p.due_date,p.amount,p.paid_amount,
               CASE WHEN p.amount-p.paid_amount < 0 THEN 0 ELSE p.amount-p.paid_amount END AS outstanding,
               p.currency,p.fx_to_base,p.base_currency,p.status,p.notes
        FROM payables p
        WHERE (p.amount-p.paid_amount) > 0.0001
          AND p.status != 'İptal'
        ORDER BY p.due_date ASC,p.id ASC
    """)
    if df.empty:
        return df
    today = pd.Timestamp(date.today())
    due = pd.to_datetime(df["due_date"], errors="coerce")
    df["days_overdue"] = (today - due).dt.days.fillna(0).astype(int)
    df["days_overdue"] = df["days_overdue"].clip(lower=0)
    df["outstanding_base"] = df["outstanding"] * df["fx_to_base"].fillna(1)
    df["risk"] = df.apply(
        lambda r:
            "GECİKMİŞ" if r["days_overdue"] > 0 else "AÇIK",
        axis=1
    )
    return df


def cash_position_base(base_currency="EUR"):
    accounts = query_df("""
        SELECT id,name,currency,balance,fx_to_base,base_currency,account_type
        FROM cash_accounts
        WHERE active=1 AND base_currency=?
    """, (base_currency,))
    if accounts.empty:
        return 0.0
    return float((accounts["balance"] * accounts["fx_to_base"].fillna(1)).sum())


def cash_forecast(base_currency="EUR", horizons=(30,60,90)):
    opening_cash = cash_position_base(base_currency)
    rec = outstanding_receivables()
    pay = outstanding_payables()
    if not rec.empty:
        rec = rec[rec["base_currency"] == base_currency].copy()
    if not pay.empty:
        pay = pay[pay["base_currency"] == base_currency].copy()
    events = query_df("""
        SELECT id,event_date,direction,category,description,amount,currency,
               fx_to_base,base_currency,status
        FROM cash_events
        WHERE status='Planlı' AND base_currency=?
        ORDER BY event_date
    """, (base_currency,))
    today = pd.Timestamp(date.today())
    rows = []
    for horizon in horizons:
        cutoff = today + pd.Timedelta(days=int(horizon))
        inflow = 0.0
        outflow = 0.0

        if not rec.empty:
            r_due = pd.to_datetime(rec["due_date"], errors="coerce")
            inflow += float(rec.loc[r_due <= cutoff, "outstanding_base"].sum())

        if not pay.empty:
            p_due = pd.to_datetime(pay["due_date"], errors="coerce")
            outflow += float(pay.loc[p_due <= cutoff, "outstanding_base"].sum())

        if not events.empty:
            e_due = pd.to_datetime(events["event_date"], errors="coerce")
            eligible = events[e_due <= cutoff].copy()
            eligible["base_amount"] = eligible["amount"] * eligible["fx_to_base"].fillna(1)
            inflow += float(
                eligible.loc[eligible["direction"]=="Giriş","base_amount"].sum()
            )
            outflow += float(
                eligible.loc[eligible["direction"]=="Çıkış","base_amount"].sum()
            )

        rows.append({
            "Gün": int(horizon),
            "Başlangıç Nakit": opening_cash,
            "Beklenen Tahsilat": inflow,
            "Beklenen Ödeme": outflow,
            "Net Hareket": inflow-outflow,
            "Tahmini Nakit": opening_cash+inflow-outflow,
            "Para": base_currency,
        })
    return pd.DataFrame(rows)


def record_receivable_payment(receivable_id, amount, transaction_date,
                              account_id, reference, notes):
    row = query_df("SELECT * FROM receivables WHERE id=?", (int(receivable_id),))
    if row.empty:
        return False, "Alacak kaydı bulunamadı."
    r = row.iloc[0]
    outstanding = max(float(r["amount"] or 0)-float(r["paid_amount"] or 0),0)
    amount = float(amount or 0)
    if amount <= 0:
        return False, "Tahsilat tutarı sıfırdan büyük olmalı."
    if amount > outstanding + 0.0001:
        return False, "Tahsilat kalan alacaktan büyük olamaz."

    new_paid = float(r["paid_amount"] or 0)+amount
    status = "Kapandı" if new_paid + 0.0001 >= float(r["amount"] or 0) else "Kısmi"
    execute(
        "UPDATE receivables SET paid_amount=?,status=? WHERE id=?",
        (new_paid,status,int(receivable_id))
    )
    execute(
        """INSERT INTO finance_transactions
        (transaction_type,receivable_id,transaction_date,amount,currency,
         fx_to_base,base_currency,account_id,reference,notes)
        VALUES ('Tahsilat',?,?,?,?,?,?,?,?,?)""",
        (
            int(receivable_id),str(transaction_date),amount,r["currency"],
            float(r["fx_to_base"] or 1),r["base_currency"] or "EUR",
            int(account_id) if account_id else None,reference,notes
        )
    )
    if account_id:
        account = query_df("SELECT * FROM cash_accounts WHERE id=?", (int(account_id),))
        if not account.empty:
            a=account.iloc[0]
            if str(a["currency"]) == str(r["currency"]):
                execute(
                    "UPDATE cash_accounts SET balance=balance+?,updated_at=? WHERE id=?",
                    (amount,datetime.now().isoformat(timespec="seconds"),int(account_id))
                )
    return True, "Tahsilat kaydedildi."


def record_payable_payment(payable_id, amount, transaction_date,
                           account_id, reference, notes):
    row = query_df("SELECT * FROM payables WHERE id=?", (int(payable_id),))
    if row.empty:
        return False, "Borç kaydı bulunamadı."
    p = row.iloc[0]
    outstanding = max(float(p["amount"] or 0)-float(p["paid_amount"] or 0),0)
    amount = float(amount or 0)
    if amount <= 0:
        return False, "Ödeme tutarı sıfırdan büyük olmalı."
    if amount > outstanding + 0.0001:
        return False, "Ödeme kalan borçtan büyük olamaz."

    new_paid = float(p["paid_amount"] or 0)+amount
    status = "Kapandı" if new_paid + 0.0001 >= float(p["amount"] or 0) else "Kısmi"
    execute(
        "UPDATE payables SET paid_amount=?,status=? WHERE id=?",
        (new_paid,status,int(payable_id))
    )
    execute(
        """INSERT INTO finance_transactions
        (transaction_type,payable_id,transaction_date,amount,currency,
         fx_to_base,base_currency,account_id,reference,notes)
        VALUES ('Ödeme',?,?,?,?,?,?,?,?,?)""",
        (
            int(payable_id),str(transaction_date),amount,p["currency"],
            float(p["fx_to_base"] or 1),p["base_currency"] or "EUR",
            int(account_id) if account_id else None,reference,notes
        )
    )
    if account_id:
        account = query_df("SELECT * FROM cash_accounts WHERE id=?", (int(account_id),))
        if not account.empty:
            a=account.iloc[0]
            if str(a["currency"]) == str(p["currency"]):
                execute(
                    "UPDATE cash_accounts SET balance=balance-?,updated_at=? WHERE id=?",
                    (amount,datetime.now().isoformat(timespec="seconds"),int(account_id))
                )
    return True, "Ödeme kaydedildi."


def calculate_quote(
    quantity_kg,
    buy_price_per_kg,
    buy_fx_to_base,
    freight_total_base,
    customs_rate_pct,
    customs_fixed_base,
    import_other_total_base,
    handling_total_base,
    finance_rate_pct,
    prepayment_days,
    stock_days,
    customer_credit_days,
    sell_price_per_kg,
    sell_fx_to_base,
    sales_commission_pct,
    target_margin_pct,
):
    qty = max(float(quantity_kg or 0), 0.0)
    if qty <= 0:
        return {
            "goods_total_base": 0.0,
            "customs_total_base": 0.0,
            "landed_before_finance": 0.0,
            "landed_cost_per_kg": 0.0,
            "finance_days": 0,
            "finance_cost_total": 0.0,
            "finance_cost_per_kg": 0.0,
            "total_cost_base": 0.0,
            "total_cost_per_kg": 0.0,
            "gross_sales_base": 0.0,
            "sales_commission_base": 0.0,
            "net_sales_base": 0.0,
            "profit_total_base": 0.0,
            "profit_per_kg": 0.0,
            "margin_pct": 0.0,
            "markup_pct": 0.0,
            "required_sell_price": 0.0,
        }

    goods_total_base = qty * float(buy_price_per_kg or 0) * float(buy_fx_to_base or 0)
    customs_total_base = (
        goods_total_base * float(customs_rate_pct or 0) / 100.0
        + float(customs_fixed_base or 0)
    )
    landed_before_finance = (
        goods_total_base
        + float(freight_total_base or 0)
        + customs_total_base
        + float(import_other_total_base or 0)
        + float(handling_total_base or 0)
    )
    landed_cost_per_kg = landed_before_finance / qty

    finance_days = max(
        0,
        int(prepayment_days or 0)
        + int(stock_days or 0)
        + int(customer_credit_days or 0),
    )
    finance_cost_total = (
        landed_before_finance
        * float(finance_rate_pct or 0)
        / 100.0
        * finance_days
        / 365.0
    )
    finance_cost_per_kg = finance_cost_total / qty
    total_cost_base = landed_before_finance + finance_cost_total
    total_cost_per_kg = total_cost_base / qty

    gross_sales_base = qty * float(sell_price_per_kg or 0) * float(sell_fx_to_base or 0)
    sales_commission_base = gross_sales_base * float(sales_commission_pct or 0) / 100.0
    net_sales_base = gross_sales_base - sales_commission_base
    profit_total_base = net_sales_base - total_cost_base
    profit_per_kg = profit_total_base / qty

    margin_pct = (
        profit_total_base / net_sales_base * 100.0
        if net_sales_base > 0 else 0.0
    )
    markup_pct = (
        profit_total_base / total_cost_base * 100.0
        if total_cost_base > 0 else 0.0
    )

    target_margin = min(max(float(target_margin_pct or 0), 0.0), 95.0) / 100.0
    commission_rate = min(max(float(sales_commission_pct or 0), 0.0), 95.0) / 100.0
    required_net_sales_per_kg_base = (
        total_cost_per_kg / (1.0 - target_margin)
        if target_margin < 1.0 else 0.0
    )
    required_gross_per_kg_base = (
        required_net_sales_per_kg_base / (1.0 - commission_rate)
        if commission_rate < 1.0 else 0.0
    )
    sell_fx = float(sell_fx_to_base or 0)
    required_sell_price = (
        required_gross_per_kg_base / sell_fx if sell_fx > 0 else 0.0
    )

    return {
        "goods_total_base": goods_total_base,
        "customs_total_base": customs_total_base,
        "landed_before_finance": landed_before_finance,
        "landed_cost_per_kg": landed_cost_per_kg,
        "finance_days": finance_days,
        "finance_cost_total": finance_cost_total,
        "finance_cost_per_kg": finance_cost_per_kg,
        "total_cost_base": total_cost_base,
        "total_cost_per_kg": total_cost_per_kg,
        "gross_sales_base": gross_sales_base,
        "sales_commission_base": sales_commission_base,
        "net_sales_base": net_sales_base,
        "profit_total_base": profit_total_base,
        "profit_per_kg": profit_per_kg,
        "margin_pct": margin_pct,
        "markup_pct": markup_pct,
        "required_sell_price": required_sell_price,
    }


def save_quote(customer_id, opportunity_id, product_name, inputs, calc):
    execute(
        """INSERT INTO quotes
        (customer_id,opportunity_id,product_name,quantity_kg,base_currency,
         buy_price_per_kg,buy_currency,buy_fx_to_base,freight_total_base,
         customs_rate_pct,customs_fixed_base,import_other_total_base,
         handling_total_base,finance_rate_pct,prepayment_days,stock_days,
         customer_credit_days,sell_price_per_kg,sell_currency,sell_fx_to_base,
         sales_commission_pct,target_margin_pct,incoterm,valid_until,status,notes,
         landed_cost_per_kg,finance_cost_per_kg,total_cost_per_kg,profit_per_kg,
         profit_total_base,margin_pct,required_sell_price,finance_days)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (
            int(customer_id) if customer_id else None,
            int(opportunity_id) if opportunity_id else None,
            product_name,
            float(inputs["quantity_kg"]),
            inputs["base_currency"],
            float(inputs["buy_price_per_kg"]),
            inputs["buy_currency"],
            float(inputs["buy_fx_to_base"]),
            float(inputs["freight_total_base"]),
            float(inputs["customs_rate_pct"]),
            float(inputs["customs_fixed_base"]),
            float(inputs["import_other_total_base"]),
            float(inputs["handling_total_base"]),
            float(inputs["finance_rate_pct"]),
            int(inputs["prepayment_days"]),
            int(inputs["stock_days"]),
            int(inputs["customer_credit_days"]),
            float(inputs["sell_price_per_kg"]),
            inputs["sell_currency"],
            float(inputs["sell_fx_to_base"]),
            float(inputs["sales_commission_pct"]),
            float(inputs["target_margin_pct"]),
            inputs["incoterm"],
            str(inputs["valid_until"]),
            inputs["status"],
            inputs["notes"],
            float(calc["landed_cost_per_kg"]),
            float(calc["finance_cost_per_kg"]),
            float(calc["total_cost_per_kg"]),
            float(calc["profit_per_kg"]),
            float(calc["profit_total_base"]),
            float(calc["margin_pct"]),
            float(calc["required_sell_price"]),
            int(calc["finance_days"]),
        )
    )


def render_control_tower():
    init_db()
    seed_once()
    seed_product_catalog()
    seed_warehouses()

    st.subheader("🧭 AS CONTROL TOWER")
    st.caption("CRM • satış hunisi • takip • görev • yönetici karar merkezi")

    dashboard, customers_tab, intelligence_tab, pricing_tab, procurement_tab, finance_tab, pipeline_tab, followup_tab, tasks_tab, ceo_tab = st.tabs(
        [
            "📊 Yönetici Paneli",
            "👥 CRM / Müşteri 360",
            "🧠 Ürün × Müşteri",
            "🧮 Teklif & Kârlılık",
            "🚚 Satın Alma & Stok",
            "💶 Finans & Nakit",
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

        rec_dashboard = outstanding_receivables()
        pay_dashboard = outstanding_payables()
        if not rec_dashboard.empty:
            rec_dashboard = rec_dashboard[rec_dashboard["base_currency"]=="EUR"].copy()
        if not pay_dashboard.empty:
            pay_dashboard = pay_dashboard[pay_dashboard["base_currency"]=="EUR"].copy()
        open_rec_base = float(rec_dashboard["outstanding_base"].sum()) if not rec_dashboard.empty else 0.0
        overdue_rec_base = float(
            rec_dashboard.loc[rec_dashboard["days_overdue"]>0,"outstanding_base"].sum()
        ) if not rec_dashboard.empty else 0.0
        open_pay_base = float(pay_dashboard["outstanding_base"].sum()) if not pay_dashboard.empty else 0.0
        cash_base = cash_position_base("EUR")
        st.caption(
            f"Nakit: {cash_base:,.0f} EUR · Açık alacak: {open_rec_base:,.0f} EUR · "
            f"Gecikmiş alacak: {overdue_rec_base:,.0f} EUR · Açık borç: {open_pay_base:,.0f} EUR"
        )

        stock_df_dashboard = stock_snapshot()
        if not stock_df_dashboard.empty:
            critical_stock = int(
                (stock_df_dashboard["status"] != "OK").sum()
            )
            inbound_total = float(stock_df_dashboard["inbound_kg"].sum())
            st.caption(
                f"Stok uyarısı: {critical_stock} ürün · Yolda: {inbound_total/1000:,.1f} ton"
            )

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

        st.markdown("#### En güçlü yeni cross-sell önerileri")
        dashboard_recs = recommendation_rows()
        if dashboard_recs.empty:
            st.info("Ürün-müşteri eşleşmesi için müşteri sektör bilgilerini ve ürün kataloğunu doldurun.")
        else:
            st.dataframe(
                dashboard_recs[
                    ["Müşteri", "Ürün", "Fit Score", "Neden", "Sorumlu"]
                ].head(8),
                use_container_width=True,
                hide_index=True,
                column_config={
                    "Fit Score": st.column_config.ProgressColumn(
                        "Fit Score", min_value=0, max_value=100
                    )
                },
            )

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
                    e7,e8=st.columns(2)
                    credit_limit=e7.number_input(
                        "Kredi limiti",
                        min_value=0.0,
                        value=float(customer["credit_limit"] or 0),
                        step=10000.0
                    )
                    default_payment_days=e8.number_input(
                        "Standart vade (gün)",
                        min_value=0,
                        value=int(customer["default_payment_days"] or 90),
                        step=5
                    )
                    profile = st.text_area(
                        "Üretim / ürün profili",
                        value=customer["product_profile"] or "",
                        placeholder="Örn: bisküvi, gofret, çikolata, kek, dolgu kreması..."
                    )
                    tiers = ["A", "B", "C"]
                    current_tier = customer["priority_tier"] if customer["priority_tier"] in tiers else "B"
                    priority_tier = st.selectbox(
                        "Müşteri önceliği",
                        tiers,
                        index=tiers.index(current_tier)
                    )
                    notes = st.text_area("Not", value=customer["notes"] or "")
                    if st.form_submit_button("Müşteri kartını güncelle"):
                        execute(
                            """UPDATE customers
                               SET country=?,sector=?,status=?,owner=?,
                                   annual_potential=?,currency=?,product_profile=?,
                                   priority_tier=?,credit_limit=?,default_payment_days=?,notes=?
                               WHERE id=?""",
                            (
                                country, sector, status, owner, potential, currency,
                                profile, priority_tier, float(credit_limit),
                                int(default_payment_days), notes, customer_id
                            )
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

    with intelligence_tab:
        st.markdown("### 🧠 Ürün × Müşteri Satış Zekâsı")
        st.caption(
            "Müşteri sektörünü, üretim profilini, ürün kataloğunu ve mevcut fırsatları "
            "birleştirerek yeni cross-sell fırsatları üretir."
        )

        intel1, intel2, intel3, intel4 = st.tabs(
            [
                "🎯 Müşteriye ne satarız?",
                "📦 Bu ürünü kime satarız?",
                "🔥 En güçlü öneriler",
                "🧾 Ürün kataloğu",
            ]
        )

        customers_intel = query_df("""
            SELECT id,name,sector,status,owner,product_profile,priority_tier
            FROM customers
            WHERE COALESCE(status,'') != 'Satın Alma Adayı'
              AND COALESCE(source,'') != 'Üretici Bulucu'
            ORDER BY name
        """)
        products_intel = query_df("""
            SELECT id,name,category,supplier,target_sectors,applications,
                   default_currency,default_opportunity_value
            FROM product_catalog
            WHERE active=1
            ORDER BY name
        """)

        with intel1:
            if customers_intel.empty:
                st.info("Önce CRM'e müşteri ekleyin.")
            else:
                customer_name = st.selectbox(
                    "Müşteri seç",
                    customers_intel["name"].tolist(),
                    key="intel_customer_select"
                )
                cid = int(
                    customers_intel.loc[
                        customers_intel["name"] == customer_name, "id"
                    ].iloc[0]
                )
                cust = customers_intel[
                    customers_intel["id"] == cid
                ].iloc[0]
                st.caption(
                    f"Sektör: {cust['sector'] or '-'} · "
                    f"Profil: {cust['product_profile'] or '-'} · "
                    f"Öncelik: {cust['priority_tier'] or 'B'}"
                )

                recs = recommendation_rows(customer_id=cid)
                if recs.empty:
                    st.info(
                        "Yeni öneri bulunamadı. Müşteri üretim profilini zenginleştirin "
                        "veya mevcut ürün durumlarını kontrol edin."
                    )
                else:
                    st.dataframe(
                        recs[
                            ["Ürün","Kategori","Fit Score","Neden","Durum",
                             "Önerilen Fırsat Değeri","Para","Uygulama"]
                        ],
                        use_container_width=True,
                        hide_index=True,
                        column_config={
                            "Fit Score": st.column_config.ProgressColumn(
                                "Fit Score", min_value=0, max_value=100
                            )
                        },
                    )
                    selected_idx = st.selectbox(
                        "Fırsata çevrilecek öneri",
                        list(range(len(recs))),
                        format_func=lambda i: (
                            f"{recs.iloc[i]['Ürün']} · skor {recs.iloc[i]['Fit Score']}"
                        ),
                        key="intel_customer_rec"
                    )
                    selected = recs.iloc[selected_idx]
                    r1, r2 = st.columns(2)
                    value = r1.number_input(
                        "Fırsat değeri",
                        min_value=0.0,
                        value=float(selected["Önerilen Fırsat Değeri"]),
                        step=10000.0,
                        key="intel_customer_value"
                    )
                    owner = r2.text_input(
                        "Sorumlu",
                        value=str(selected["Sorumlu"] or ""),
                        key="intel_customer_owner"
                    )
                    if st.button(
                        "Bu öneriyi satış fırsatına çevir",
                        type="primary",
                        use_container_width=True,
                        key="intel_customer_create"
                    ):
                        ok, msg = create_opportunity_from_recommendation(
                            int(selected["customer_id"]),
                            int(selected["product_id"]),
                            value,
                            owner
                        )
                        if ok:
                            st.success(msg)
                            st.rerun()
                        else:
                            st.warning(msg)

                st.divider()
                st.markdown("##### Bu müşteride ürün durumunu öğret")
                if not products_intel.empty:
                    p_name = st.selectbox(
                        "Ürün",
                        products_intel["name"].tolist(),
                        key="intel_status_product"
                    )
                    pid = int(
                        products_intel.loc[
                            products_intel["name"] == p_name, "id"
                        ].iloc[0]
                    )
                    x1, x2 = st.columns(2)
                    status = x1.selectbox(
                        "Durum",
                        ["Potansiyel", "Mevcut", "Rakipte", "Uygun Değil"],
                        key="intel_status_value"
                    )
                    current_supplier = x2.text_input(
                        "Mevcut / rakip tedarikçi",
                        key="intel_status_supplier"
                    )
                    annual_volume = st.number_input(
                        "Tahmini yıllık hacim (ton)",
                        min_value=0.0,
                        step=10.0,
                        key="intel_status_volume"
                    )
                    status_notes = st.text_input(
                        "Not",
                        key="intel_status_notes"
                    )
                    if st.button(
                        "Ürün durumunu kaydet",
                        use_container_width=True,
                        key="intel_status_save"
                    ):
                        save_customer_product_status(
                            cid, pid, status, current_supplier,
                            annual_volume, status_notes
                        )
                        st.success("Müşteri-ürün bilgisi kaydedildi.")
                        st.rerun()

        with intel2:
            if products_intel.empty:
                st.info("Ürün kataloğu boş.")
            else:
                product_name = st.selectbox(
                    "Ürün seç",
                    products_intel["name"].tolist(),
                    key="intel_product_select"
                )
                pid = int(
                    products_intel.loc[
                        products_intel["name"] == product_name, "id"
                    ].iloc[0]
                )
                product_row = products_intel[
                    products_intel["id"] == pid
                ].iloc[0]
                st.caption(
                    f"{product_row['category']} · {product_row['applications']} · "
                    f"Hedef sektörler: {product_row['target_sectors']}"
                )
                recs = recommendation_rows(product_id=pid)
                if recs.empty:
                    st.info("Bu ürün için yeni müşteri eşleşmesi bulunamadı.")
                else:
                    st.dataframe(
                        recs[
                            ["Müşteri","Fit Score","Neden","Durum","Sorumlu",
                             "Önerilen Fırsat Değeri","Para"]
                        ],
                        use_container_width=True,
                        hide_index=True,
                        column_config={
                            "Fit Score": st.column_config.ProgressColumn(
                                "Fit Score", min_value=0, max_value=100
                            )
                        },
                    )
                    selected_idx = st.selectbox(
                        "Fırsata çevrilecek müşteri",
                        list(range(len(recs))),
                        format_func=lambda i: (
                            f"{recs.iloc[i]['Müşteri']} · skor {recs.iloc[i]['Fit Score']}"
                        ),
                        key="intel_product_rec"
                    )
                    selected = recs.iloc[selected_idx]
                    y1, y2 = st.columns(2)
                    value = y1.number_input(
                        "Fırsat değeri",
                        min_value=0.0,
                        value=float(selected["Önerilen Fırsat Değeri"]),
                        step=10000.0,
                        key="intel_product_value"
                    )
                    owner = y2.text_input(
                        "Sorumlu",
                        value=str(selected["Sorumlu"] or ""),
                        key="intel_product_owner"
                    )
                    if st.button(
                        "Bu müşteride fırsat oluştur",
                        type="primary",
                        use_container_width=True,
                        key="intel_product_create"
                    ):
                        ok, msg = create_opportunity_from_recommendation(
                            int(selected["customer_id"]),
                            int(selected["product_id"]),
                            value,
                            owner
                        )
                        if ok:
                            st.success(msg)
                            st.rerun()
                        else:
                            st.warning(msg)

        with intel3:
            all_recs = recommendation_rows()
            if all_recs.empty:
                st.info("Henüz güçlü ürün-müşteri eşleşmesi oluşmadı.")
            else:
                min_score = st.slider(
                    "Minimum Fit Score",
                    0, 100, 60,
                    key="intel_min_score"
                )
                view = all_recs[all_recs["Fit Score"] >= min_score].copy()
                st.metric("Yeni öneri", len(view))
                st.dataframe(
                    view[
                        ["Müşteri","Ürün","Kategori","Fit Score","Neden",
                         "Durum","Sorumlu","Önerilen Fırsat Değeri","Para"]
                    ],
                    use_container_width=True,
                    hide_index=True,
                    column_config={
                        "Fit Score": st.column_config.ProgressColumn(
                            "Fit Score", min_value=0, max_value=100
                        )
                    },
                )

        with intel4:
            st.dataframe(
                products_intel,
                use_container_width=True,
                hide_index=True
            )
            with st.expander("Yeni ürün ekle"):
                with st.form("intel_new_product", clear_on_submit=True):
                    name = st.text_input("Ürün adı *")
                    p1, p2 = st.columns(2)
                    category = p1.text_input("Kategori")
                    supplier = p2.text_input("Tedarikçi")
                    supplier_country = st.text_input("Tedarikçi ülkesi")
                    target_sectors = st.text_area(
                        "Hedef sektör anahtarları",
                        placeholder="bisküvi;çikolata;bakery;dairy;meat"
                    )
                    applications = st.text_area("Uygulamalar / kullanım alanları")
                    p3, p4 = st.columns(2)
                    currency = p3.selectbox(
                        "Para",
                        ["EUR","USD","GBP","TRY"]
                    )
                    default_value = p4.number_input(
                        "Varsayılan fırsat değeri",
                        min_value=0.0,
                        value=100000.0,
                        step=10000.0
                    )
                    notes = st.text_area("Not")
                    if st.form_submit_button("Ürünü kataloğa ekle", type="primary") and name.strip():
                        exists = int(query_df(
                            "SELECT COUNT(*) n FROM product_catalog WHERE lower(name)=lower(?)",
                            (name.strip(),)
                        ).iloc[0]["n"])
                        if exists:
                            st.warning("Bu ürün zaten katalogda.")
                        else:
                            execute(
                                """INSERT INTO product_catalog
                                (name,category,supplier,supplier_country,target_sectors,
                                 applications,default_currency,default_opportunity_value,
                                 active,notes)
                                VALUES (?,?,?,?,?,?,?,?,1,?)""",
                                (
                                    name.strip(), category, supplier, supplier_country,
                                    target_sectors, applications, currency,
                                    float(default_value), notes
                                )
                            )
                            st.success("Ürün kataloğa eklendi.")
                            st.rerun()

    with pricing_tab:
        st.markdown("### 🧮 Teklif + Gerçek Maliyet + Kârlılık Motoru")
        st.caption(
            "Alış, kur, navlun, gümrük, ithalat/depo gideri ve finansman süresini "
            "tek maliyette toplar. KDV bu V1 hesapta kâr maliyetine dahil edilmez; "
            "indirilemeyen vergi/harç varsa 'Diğer ithalat gideri'ne ekleyin."
        )

        quote_tab, history_tab = st.tabs(["Yeni Hesap / Teklif", "Teklif Geçmişi"])

        with quote_tab:
            customers_q = query_df(
                "SELECT id,name,owner FROM customers ORDER BY name"
            )
            products_q = query_df(
                "SELECT id,name,default_currency FROM product_catalog WHERE active=1 ORDER BY name"
            )
            opportunities_q = query_df("""
                SELECT o.id,c.name AS customer_name,o.customer_id,o.product,o.owner,o.stage
                FROM opportunities o
                LEFT JOIN customers c ON c.id=o.customer_id
                WHERE o.stage NOT IN ('Kaybedildi')
                ORDER BY o.id DESC
            """)

            q1, q2 = st.columns(2)
            customer_options = ["— Müşteri seçilmedi —"] + customers_q["name"].tolist()
            selected_customer_name = q1.selectbox(
                "Müşteri",
                customer_options,
                key="quote_customer"
            )
            customer_id = None
            customer_owner = ""
            if selected_customer_name != "— Müşteri seçilmedi —":
                crow = customers_q[customers_q["name"] == selected_customer_name].iloc[0]
                customer_id = int(crow["id"])
                customer_owner = str(crow["owner"] or "")

            product_options = products_q["name"].tolist() + ["Diğer / Manuel"]
            selected_product = q2.selectbox(
                "Ürün",
                product_options,
                key="quote_product"
            )
            product_name = (
                st.text_input("Manuel ürün adı", key="quote_manual_product")
                if selected_product == "Diğer / Manuel"
                else selected_product
            )

            opp_id = None
            if customer_id:
                customer_opps = opportunities_q[
                    opportunities_q["customer_id"] == customer_id
                ].copy()
                opp_labels = ["— Fırsata bağlama —"]
                opp_map = {"— Fırsata bağlama —": None}
                for _, r in customer_opps.iterrows():
                    label = f"#{int(r['id'])} · {r['product']} · {r['stage']}"
                    opp_labels.append(label)
                    opp_map[label] = int(r["id"])
                opp_label = st.selectbox(
                    "Satış fırsatı",
                    opp_labels,
                    key="quote_opportunity"
                )
                opp_id = opp_map[opp_label]

            st.markdown("##### 1. Miktar ve alış")
            a1, a2, a3, a4 = st.columns(4)
            quantity_kg = a1.number_input(
                "Miktar (kg)", min_value=1.0, value=24000.0, step=1000.0,
                key="quote_qty"
            )
            buy_price = a2.number_input(
                "Alış fiyatı / kg", min_value=0.0, value=2.00, step=0.01,
                format="%.4f", key="quote_buy_price"
            )
            buy_currency = a3.selectbox(
                "Alış para birimi", ["EUR","USD","GBP","TRY"], key="quote_buy_currency"
            )
            base_currency = a4.selectbox(
                "Hesap para birimi", ["EUR","USD","GBP","TRY"], key="quote_base_currency"
            )

            default_buy_fx = 1.0 if buy_currency == base_currency else 1.0
            buy_fx = st.number_input(
                f"1 {buy_currency} = kaç {base_currency}?",
                min_value=0.0001, value=float(default_buy_fx), step=0.01,
                format="%.4f", key="quote_buy_fx"
            )

            st.markdown("##### 2. İthalat ve lojistik maliyetleri")
            b1, b2, b3, b4 = st.columns(4)
            freight = b1.number_input(
                f"Toplam navlun ({base_currency})",
                min_value=0.0, value=0.0, step=100.0, key="quote_freight"
            )
            customs_rate = b2.number_input(
                "Gümrük oranı %", min_value=0.0, value=0.0, step=0.1,
                key="quote_customs_rate"
            )
            customs_fixed = b3.number_input(
                f"Sabit gümrük/harç ({base_currency})",
                min_value=0.0, value=0.0, step=100.0, key="quote_customs_fixed"
            )
            import_other = b4.number_input(
                f"Diğer ithalat gideri ({base_currency})",
                min_value=0.0, value=0.0, step=100.0, key="quote_import_other"
            )
            handling = st.number_input(
                f"Depo / handling / iç nakliye toplamı ({base_currency})",
                min_value=0.0, value=0.0, step=100.0, key="quote_handling"
            )

            st.markdown("##### 3. Paranın bağlı kaldığı süre")
            c1, c2, c3, c4 = st.columns(4)
            finance_rate = c1.number_input(
                "Yıllık finansman faizi %", min_value=0.0, value=45.0, step=1.0,
                key="quote_finance_rate"
            )
            prepayment_days = c2.number_input(
                "Teslimden önce ödeme (gün)", min_value=0, value=35, step=1,
                key="quote_prepay_days"
            )
            stock_days = c3.number_input(
                "Stokta bekleme (gün)", min_value=0, value=30, step=1,
                key="quote_stock_days"
            )
            customer_credit_days = c4.number_input(
                "Müşteri vadesi (gün)", min_value=0, value=105, step=5,
                key="quote_customer_days"
            )

            st.markdown("##### 4. Satış fiyatı ve hedef")
            d1, d2, d3, d4 = st.columns(4)
            sell_price = d1.number_input(
                "Satış fiyatı / kg", min_value=0.0, value=2.50, step=0.01,
                format="%.4f", key="quote_sell_price"
            )
            sell_currency = d2.selectbox(
                "Satış para birimi", ["EUR","USD","GBP","TRY"], key="quote_sell_currency"
            )
            sell_fx = d3.number_input(
                f"1 satış para birimi = kaç {base_currency}?",
                min_value=0.0001,
                value=1.0,
                step=0.01,
                format="%.4f",
                key="quote_sell_fx"
            )
            target_margin = d4.number_input(
                "Hedef net katkı marjı %", min_value=0.0, max_value=95.0,
                value=10.0, step=0.5, key="quote_target_margin"
            )
            commission = st.number_input(
                "Satış komisyonu / iskonto etkisi %", min_value=0.0, max_value=95.0,
                value=0.0, step=0.5, key="quote_commission"
            )

            calc = calculate_quote(
                quantity_kg, buy_price, buy_fx, freight, customs_rate,
                customs_fixed, import_other, handling, finance_rate,
                prepayment_days, stock_days, customer_credit_days,
                sell_price, sell_fx, commission, target_margin
            )

            st.markdown("### Sonuç")
            r1, r2, r3, r4 = st.columns(4)
            r1.metric(
                "Landed maliyet / kg",
                f"{calc['landed_cost_per_kg']:.4f} {base_currency}"
            )
            r2.metric(
                "Finansman maliyeti / kg",
                f"{calc['finance_cost_per_kg']:.4f} {base_currency}",
                help=f"Toplam {calc['finance_days']} gün finansman"
            )
            r3.metric(
                "Gerçek maliyet / kg",
                f"{calc['total_cost_per_kg']:.4f} {base_currency}"
            )
            r4.metric(
                "Net katkı / kg",
                f"{calc['profit_per_kg']:.4f} {base_currency}"
            )

            r5, r6, r7, r8 = st.columns(4)
            r5.metric(
                "Toplam net katkı",
                f"{calc['profit_total_base']:,.0f} {base_currency}"
            )
            r6.metric(
                "Net katkı marjı",
                f"%{calc['margin_pct']:.2f}"
            )
            r7.metric(
                "Maliyet üstü getiri",
                f"%{calc['markup_pct']:.2f}"
            )
            r8.metric(
                f"Hedef %{target_margin:.1f} için satış fiyatı",
                f"{calc['required_sell_price']:.4f} {sell_currency}/kg"
            )

            st.caption(
                f"Nakit döngüsü varsayımı: {int(prepayment_days)} gün erken ödeme + "
                f"{int(stock_days)} gün stok + {int(customer_credit_days)} gün müşteri vadesi "
                f"= {calc['finance_days']} gün."
            )

            if calc["profit_total_base"] < 0:
                st.error(
                    f"Bu teklif zarar yazıyor: toplam yaklaşık "
                    f"{abs(calc['profit_total_base']):,.0f} {base_currency} zarar."
                )
            elif calc["margin_pct"] + 0.0001 < target_margin:
                st.warning(
                    f"Teklif kârlı ama hedef marjın altında. Hedef fiyat yaklaşık "
                    f"{calc['required_sell_price']:.4f} {sell_currency}/kg."
                )
            else:
                st.success(
                    f"Teklif hedef marjı karşılıyor. Tahmini net katkı "
                    f"{calc['profit_total_base']:,.0f} {base_currency}."
                )

            with st.expander("Maliyet kırılımı"):
                breakdown = pd.DataFrame([
                    {"Kalem":"Mal bedeli","Tutar":calc["goods_total_base"],"Para":base_currency},
                    {"Kalem":"Gümrük / harç","Tutar":calc["customs_total_base"],"Para":base_currency},
                    {"Kalem":"Navlun","Tutar":freight,"Para":base_currency},
                    {"Kalem":"Diğer ithalat","Tutar":import_other,"Para":base_currency},
                    {"Kalem":"Depo / handling / iç nakliye","Tutar":handling,"Para":base_currency},
                    {"Kalem":"Finansman","Tutar":calc["finance_cost_total"],"Para":base_currency},
                ])
                st.dataframe(breakdown, use_container_width=True, hide_index=True)

            st.markdown("##### Teklifi kaydet")
            e1, e2, e3 = st.columns(3)
            incoterm = e1.text_input("Satış Incoterm", value="DDP", key="quote_incoterm")
            valid_until = e2.date_input(
                "Teklif geçerlilik", value=date.today() + timedelta(days=7),
                key="quote_valid_until"
            )
            quote_status = e3.selectbox(
                "Durum",
                ["Taslak","Gönderildi","Revizyon","Kabul","Red"],
                key="quote_status"
            )
            quote_notes = st.text_area(
                "Teklif notu",
                key="quote_notes"
            )

            if st.button(
                "Hesabı / teklifi kaydet",
                type="primary",
                use_container_width=True,
                key="quote_save"
            ):
                if not product_name.strip():
                    st.error("Ürün adı gerekli.")
                else:
                    inputs = {
                        "quantity_kg": quantity_kg,
                        "base_currency": base_currency,
                        "buy_price_per_kg": buy_price,
                        "buy_currency": buy_currency,
                        "buy_fx_to_base": buy_fx,
                        "freight_total_base": freight,
                        "customs_rate_pct": customs_rate,
                        "customs_fixed_base": customs_fixed,
                        "import_other_total_base": import_other,
                        "handling_total_base": handling,
                        "finance_rate_pct": finance_rate,
                        "prepayment_days": prepayment_days,
                        "stock_days": stock_days,
                        "customer_credit_days": customer_credit_days,
                        "sell_price_per_kg": sell_price,
                        "sell_currency": sell_currency,
                        "sell_fx_to_base": sell_fx,
                        "sales_commission_pct": commission,
                        "target_margin_pct": target_margin,
                        "incoterm": incoterm,
                        "valid_until": valid_until,
                        "status": quote_status,
                        "notes": quote_notes,
                    }
                    save_quote(
                        customer_id, opp_id, product_name.strip(), inputs, calc
                    )
                    if opp_id:
                        old_stage_row = query_df(
                            "SELECT stage, owner FROM opportunities WHERE id=?",
                            (int(opp_id),)
                        )
                        old_stage = (
                            str(old_stage_row.iloc[0]["stage"])
                            if not old_stage_row.empty else ""
                        )
                        opp_owner = (
                            str(old_stage_row.iloc[0]["owner"] or "")
                            if not old_stage_row.empty else customer_owner
                        )
                        execute(
                            """UPDATE opportunities
                               SET stage='Teklif', probability=?,
                                   next_action='Teklif takibi',
                                   due_date=?, updated_at=?
                               WHERE id=?""",
                            (
                                STAGE_PROBABILITY["Teklif"],
                                str(date.today() + timedelta(days=3)),
                                datetime.now().isoformat(timespec="seconds"),
                                int(opp_id),
                            )
                        )
                        if old_stage != "Teklif":
                            execute(
                                """INSERT INTO opportunity_stage_history
                                (opportunity_id,old_stage,new_stage,owner,note)
                                VALUES (?,?,'Teklif',?,?)""",
                                (
                                    int(opp_id),
                                    old_stage,
                                    opp_owner,
                                    "Teklif & Kârlılık motorundan teklif kaydedildi"
                                )
                            )
                    st.success("Teklif hesabı kaydedildi.")
                    st.rerun()

        with history_tab:
            quote_history = query_df("""
                SELECT q.id, q.created_at AS tarih, c.name AS müşteri,
                       q.product_name AS ürün, q.quantity_kg AS miktar_kg,
                       q.buy_price_per_kg AS alış, q.buy_currency AS alış_para,
                       q.sell_price_per_kg AS satış, q.sell_currency AS satış_para,
                       q.total_cost_per_kg AS gerçek_maliyet,
                       q.profit_per_kg AS katkı_kg,
                       q.margin_pct AS marj_yüzde,
                       q.profit_total_base AS toplam_katkı,
                       q.base_currency AS hesap_para,
                       q.finance_days AS finansman_gün,
                       q.required_sell_price AS hedef_fiyat,
                       q.status AS durum, q.valid_until AS geçerlilik
                FROM quotes q
                LEFT JOIN customers c ON c.id=q.customer_id
                ORDER BY q.id DESC
            """)
            st.dataframe(
                quote_history,
                use_container_width=True,
                hide_index=True
            )

    with procurement_tab:
        st.markdown("### 🚚 Satın Alma + PO + Sevkiyat + Stok")
        st.caption(
            "Siparişten depoya kadar mal akışını izler. Stok gününü ve yeniden sipariş "
            "ihtiyacını aylık tüketim + güvenlik stoğu + tedarik süresine göre hesaplar."
        )

        po_tab, ship_tab, stock_tab, reorder_tab, warehouse_tab = st.tabs(
            ["📄 Satın Alma Siparişleri", "🚛 Sevkiyatlar", "🏬 Stok", "⚠️ Yeniden Sipariş", "🏢 Depolar"]
        )

        with po_tab:
            po_df = query_df("""
                SELECT po.id,po.po_number AS PO,po.supplier AS tedarikçi,
                       po.product_name AS ürün,po.quantity_kg/1000.0 AS ton,
                       po.unit_price AS birim_fiyat,po.currency AS para,
                       po.incoterm,po.payment_terms AS ödeme,
                       po.order_date AS sipariş_tarihi,
                       po.requested_load_date AS istenen_yükleme,
                       po.confirmed_load_date AS teyitli_yükleme,
                       w.name AS depo,po.status AS durum
                FROM purchase_orders po
                LEFT JOIN warehouses w ON w.id=po.destination_warehouse_id
                ORDER BY po.id DESC
            """)
            st.dataframe(po_df,use_container_width=True,hide_index=True)

            with st.expander("Yeni PO oluştur", expanded=po_df.empty):
                products_po=query_df("""
                    SELECT id,name,supplier,default_currency
                    FROM product_catalog WHERE active=1 ORDER BY name
                """)
                warehouses_po=query_df("""
                    SELECT id,name FROM warehouses WHERE active=1 ORDER BY name
                """)
                with st.form("proc_new_po",clear_on_submit=True):
                    po_number=st.text_input("PO numarası *",placeholder="Örn: 20260004")
                    p_name=st.selectbox("Ürün",products_po["name"].tolist())
                    prow=products_po[products_po["name"]==p_name].iloc[0]
                    supplier=st.text_input("Tedarikçi *",value=str(prow["supplier"] or ""))
                    z1,z2,z3=st.columns(3)
                    qty_kg=z1.number_input("Miktar (kg)",min_value=1.0,value=24000.0,step=1000.0)
                    unit_price=z2.number_input("Alış fiyatı / kg",min_value=0.0,value=0.0,step=0.01,format="%.4f")
                    currency=z3.selectbox("Para",["EUR","USD","GBP","TRY"],index=["EUR","USD","GBP","TRY"].index(prow["default_currency"] if prow["default_currency"] in ["EUR","USD","GBP","TRY"] else "EUR"))
                    z4,z5=st.columns(2)
                    incoterm=z4.text_input("Incoterm",placeholder="EXW / FOB / CIF / DDP")
                    payment_terms=z5.text_input("Ödeme şartı",placeholder="20% prepay + 80% 30 days")
                    z6,z7,z8=st.columns(3)
                    order_date=z6.date_input("Sipariş tarihi",value=date.today())
                    requested_load=z7.date_input("İstenen yükleme",value=date.today()+timedelta(days=14))
                    confirmed_load=z8.date_input("Teyitli yükleme",value=date.today()+timedelta(days=14))
                    wh_name=st.selectbox("Hedef depo",warehouses_po["name"].tolist())
                    warehouse_id=int(warehouses_po.loc[warehouses_po["name"]==wh_name,"id"].iloc[0])
                    status=st.selectbox("Durum",["Sipariş Verildi","Teyit Bekliyor","Teyitli","Üretimde","Hazır","Kısmi Sevk","Tamamlandı","İptal"])
                    notes=st.text_area("Not")
                    if st.form_submit_button("PO kaydet",type="primary"):
                        if not po_number.strip() or not supplier.strip():
                            st.error("PO numarası ve tedarikçi zorunlu.")
                        else:
                            duplicate=int(query_df("SELECT COUNT(*) n FROM purchase_orders WHERE po_number=?",(po_number.strip(),)).iloc[0]["n"])
                            if duplicate:
                                st.error("Bu PO numarası zaten var.")
                            else:
                                execute("""INSERT INTO purchase_orders
                                    (po_number,supplier,product_id,product_name,quantity_kg,unit_price,currency,
                                     incoterm,payment_terms,order_date,requested_load_date,confirmed_load_date,
                                     destination_warehouse_id,status,notes)
                                    VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                                    (po_number.strip(),supplier.strip(),int(prow["id"]),p_name,float(qty_kg),
                                     float(unit_price),currency,incoterm,payment_terms,str(order_date),
                                     str(requested_load),str(confirmed_load),warehouse_id,status,notes))
                                st.success("PO oluşturuldu.")
                                st.rerun()

        with ship_tab:
            shipments_df=query_df("""
                SELECT s.id,po.po_number AS PO,po.supplier AS tedarikçi,po.product_name AS ürün,
                       s.quantity_kg/1000.0 AS ton,s.shipment_ref AS referans,
                       s.transport_mode AS taşıma,s.container_vehicle AS araç_konteyner,
                       s.etd,s.eta,s.customs_date AS gümrük,s.delivery_date AS teslim,
                       w.name AS depo,s.lot_number AS lot,s.expiry_date AS SKT,
                       s.status AS durum,
                       CASE WHEN s.received_to_stock=1 THEN 'Evet' ELSE '' END AS stoğa_alındı
                FROM shipments s
                JOIN purchase_orders po ON po.id=s.purchase_order_id
                LEFT JOIN warehouses w ON w.id=s.destination_warehouse_id
                ORDER BY s.id DESC
            """)
            st.dataframe(shipments_df,use_container_width=True,hide_index=True)

            with st.expander("Yeni sevkiyat oluştur"):
                pos=query_df("""
                    SELECT id,po_number,supplier,product_name,quantity_kg,destination_warehouse_id
                    FROM purchase_orders
                    WHERE status NOT IN ('Tamamlandı','İptal')
                    ORDER BY id DESC
                """)
                warehouses_s=query_df("SELECT id,name FROM warehouses WHERE active=1 ORDER BY name")
                if pos.empty:
                    st.info("Açık PO yok.")
                else:
                    with st.form("proc_new_shipment",clear_on_submit=True):
                        po_label=st.selectbox("PO",pos.apply(lambda r:f"{r['po_number']} · {r['supplier']} · {r['product_name']}",axis=1).tolist())
                        po_index=pos.apply(lambda r:f"{r['po_number']} · {r['supplier']} · {r['product_name']}",axis=1).tolist().index(po_label)
                        po_row=pos.iloc[po_index]
                        y1,y2,y3=st.columns(3)
                        ship_qty=y1.number_input("Sevk miktarı (kg)",min_value=1.0,value=float(po_row["quantity_kg"]),step=1000.0)
                        transport=y2.selectbox("Taşıma",["Tır","Konteyner","Hava","Parsiyel","Diğer"])
                        shipment_ref=y3.text_input("Sevkiyat / booking ref")
                        y4,y5=st.columns(2)
                        carrier=y4.text_input("Nakliyeci")
                        vehicle=y5.text_input("Araç / konteyner no")
                        y6,y7=st.columns(2)
                        etd=y6.date_input("ETD / çıkış",value=date.today()+timedelta(days=7))
                        eta=y7.date_input("ETA / varış",value=date.today()+timedelta(days=14))
                        wh_names=warehouses_s["name"].tolist()
                        default_wh=0
                        if po_row["destination_warehouse_id"]:
                            ids=warehouses_s["id"].tolist()
                            if int(po_row["destination_warehouse_id"]) in ids:
                                default_wh=ids.index(int(po_row["destination_warehouse_id"]))
                        wh_name=st.selectbox("Hedef depo",wh_names,index=default_wh)
                        wh_id=int(warehouses_s.loc[warehouses_s["name"]==wh_name,"id"].iloc[0])
                        lot=st.text_input("Lot no")
                        expiry=st.date_input("SKT",value=date.today()+timedelta(days=365))
                        status=st.selectbox("Durum",["Planlandı","Yükleme Bekliyor","Yüklendi","Yolda","Limanda / Sınırda","Gümrükte","Dağıtımda","Teslim Edildi","İptal"])
                        notes=st.text_area("Not")
                        if st.form_submit_button("Sevkiyat kaydet",type="primary"):
                            execute("""INSERT INTO shipments
                                (purchase_order_id,shipment_ref,quantity_kg,transport_mode,carrier,
                                 container_vehicle,etd,eta,status,destination_warehouse_id,
                                 lot_number,expiry_date,notes)
                                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                                (int(po_row["id"]),shipment_ref,float(ship_qty),transport,carrier,
                                 vehicle,str(etd),str(eta),status,wh_id,lot,str(expiry),notes))
                            execute("UPDATE purchase_orders SET status='Kısmi Sevk' WHERE id=?",(int(po_row["id"]),))
                            st.success("Sevkiyat oluşturuldu.")
                            st.rerun()

            if not shipments_df.empty:
                st.markdown("##### Sevkiyat durumunu güncelle / stoğa al")
                ship_id=st.selectbox(
                    "Sevkiyat",
                    shipments_df["id"].tolist(),
                    format_func=lambda x:f"#{x} · {shipments_df.loc[shipments_df['id']==x,'PO'].iloc[0]} · {shipments_df.loc[shipments_df['id']==x,'ürün'].iloc[0]}",
                    key="proc_ship_update"
                )
                raw=query_df("SELECT * FROM shipments WHERE id=?",(int(ship_id),)).iloc[0]
                u1,u2,u3=st.columns(3)
                ship_statuses=["Planlandı","Yükleme Bekliyor","Yüklendi","Yolda","Limanda / Sınırda","Gümrükte","Dağıtımda","Teslim Edildi","İptal"]
                current_status=raw["status"] if raw["status"] in ship_statuses else "Planlandı"
                new_status=u1.selectbox("Yeni durum",ship_statuses,index=ship_statuses.index(current_status))
                customs_date=u2.date_input("Gümrük tarihi",value=date.today(),key="proc_customs_date")
                delivery_date=u3.date_input("Teslim tarihi",value=date.today(),key="proc_delivery_date")
                c1,c2=st.columns(2)
                if c1.button("Sevkiyatı güncelle",use_container_width=True):
                    execute("""UPDATE shipments SET status=?,
                               customs_date=CASE WHEN ?='Gümrükte' THEN ? ELSE customs_date END,
                               delivery_date=CASE WHEN ?='Teslim Edildi' THEN ? ELSE delivery_date END
                               WHERE id=?""",
                            (new_status,new_status,str(customs_date),new_status,str(delivery_date),int(ship_id)))
                    st.success("Sevkiyat güncellendi.")
                    st.rerun()
                if c2.button("Teslim al ve stoğa giriş yap",type="primary",use_container_width=True):
                    ok,msg=receive_shipment_to_stock(ship_id)
                    (st.success if ok else st.warning)(msg)
                    if ok:
                        st.rerun()

        with stock_tab:
            stock_by_lot=query_df("""
                SELECT il.id,il.product_name AS ürün,w.name AS depo,
                       il.lot_number AS lot,il.expiry_date AS SKT,
                       il.quantity_received_kg/1000.0 AS giriş_ton,
                       il.quantity_available_kg/1000.0 AS mevcut_ton,
                       il.quantity_reserved_kg/1000.0 AS rezerve_ton,
                       il.unit_cost AS birim_maliyet,il.currency AS para,
                       il.received_date AS giriş_tarihi,po.po_number AS PO
                FROM inventory_lots il
                JOIN warehouses w ON w.id=il.warehouse_id
                LEFT JOIN purchase_orders po ON po.id=il.purchase_order_id
                ORDER BY il.received_date DESC,il.id DESC
            """)
            st.dataframe(stock_by_lot,use_container_width=True,hide_index=True)

            summary=stock_snapshot()
            st.markdown("##### Ürün bazında stok özeti")
            if summary.empty:
                st.info("Henüz stok verisi yok.")
            else:
                stock_view=summary.rename(columns={
                    "name":"ürün","supplier":"tedarikçi","net_available_kg":"net_stok_kg",
                    "inbound_kg":"yolda_kg","monthly_usage_kg":"aylık_tüketim_kg",
                    "stock_days":"stok_gün","suggested_order_kg":"önerilen_sipariş_kg",
                    "status":"durum"
                })
                st.dataframe(
                    stock_view[["ürün","tedarikçi","net_stok_kg","yolda_kg","aylık_tüketim_kg",
                                "stok_gün","safety_stock_days","lead_time_days",
                                "önerilen_sipariş_kg","durum"]],
                    use_container_width=True,hide_index=True
                )

            st.markdown("##### Manuel stok düzeltmesi / rezervasyon")
            if not stock_by_lot.empty:
                lot_id=st.selectbox(
                    "Stok lotu",
                    stock_by_lot["id"].tolist(),
                    format_func=lambda x:f"#{x} · {stock_by_lot.loc[stock_by_lot['id']==x,'ürün'].iloc[0]} · {stock_by_lot.loc[stock_by_lot['id']==x,'depo'].iloc[0]}",
                    key="proc_lot_select"
                )
                lotrow=query_df("SELECT * FROM inventory_lots WHERE id=?",(int(lot_id),)).iloc[0]
                l1,l2=st.columns(2)
                available=l1.number_input("Mevcut miktar (kg)",min_value=0.0,value=float(lotrow["quantity_available_kg"] or 0),step=100.0)
                reserved=l2.number_input("Rezerve miktar (kg)",min_value=0.0,value=float(lotrow["quantity_reserved_kg"] or 0),step=100.0)
                if st.button("Stok miktarını güncelle"):
                    execute("UPDATE inventory_lots SET quantity_available_kg=?,quantity_reserved_kg=? WHERE id=?",
                            (float(available),float(reserved),int(lot_id)))
                    st.success("Stok güncellendi.")
                    st.rerun()

        with reorder_tab:
            summary=stock_snapshot()
            if summary.empty:
                st.info("Ürün kataloğu veya stok politikası yok.")
            else:
                alerts=summary[summary["status"]!="OK"].copy()
                st.metric("Sipariş / stok uyarısı",len(alerts))
                if alerts.empty:
                    st.success("Tanımlı tüketim politikalarına göre kritik ürün görünmüyor.")
                else:
                    view=alerts.rename(columns={
                        "name":"ürün","supplier":"tedarikçi","net_available_kg":"net_stok_kg",
                        "inbound_kg":"yolda_kg","monthly_usage_kg":"aylık_tüketim_kg",
                        "stock_days":"stok_gün","reorder_point_kg":"sipariş_noktası_kg",
                        "suggested_order_kg":"önerilen_sipariş_kg","status":"durum"
                    })
                    st.dataframe(
                        view[["ürün","tedarikçi","net_stok_kg","yolda_kg","aylık_tüketim_kg",
                              "stok_gün","lead_time_days","safety_stock_days",
                              "sipariş_noktası_kg","önerilen_sipariş_kg","durum"]],
                        use_container_width=True,hide_index=True
                    )

                st.markdown("##### Ürün stok politikası")
                products_pol=query_df("SELECT id,name FROM product_catalog WHERE active=1 ORDER BY name")
                pol_name=st.selectbox("Ürün",products_pol["name"].tolist(),key="proc_policy_product")
                pid=int(products_pol.loc[products_pol["name"]==pol_name,"id"].iloc[0])
                current=query_df("SELECT * FROM inventory_policy WHERE product_id=?",(pid,))
                if current.empty:
                    monthly=0.0; safety=30; lead=45; review=7; pnotes=""
                else:
                    cr=current.iloc[0]
                    monthly=float(cr["monthly_usage_kg"] or 0); safety=int(cr["safety_stock_days"] or 30)
                    lead=int(cr["lead_time_days"] or 45); review=int(cr["reorder_review_days"] or 7); pnotes=str(cr["notes"] or "")
                p1,p2,p3,p4=st.columns(4)
                monthly_new=p1.number_input("Aylık tüketim (kg)",min_value=0.0,value=monthly,step=1000.0,key="proc_policy_monthly")
                safety_new=p2.number_input("Güvenlik stoğu (gün)",min_value=0,value=safety,step=5,key="proc_policy_safety")
                lead_new=p3.number_input("Tedarik süresi (gün)",min_value=0,value=lead,step=5,key="proc_policy_lead")
                review_new=p4.number_input("Sipariş gözden geçirme (gün)",min_value=0,value=review,step=1,key="proc_policy_review")
                pnotes_new=st.text_input("Politika notu",value=pnotes,key="proc_policy_notes")
                if st.button("Stok politikasını kaydet",type="primary"):
                    execute("""INSERT INTO inventory_policy
                        (product_id,monthly_usage_kg,safety_stock_days,lead_time_days,reorder_review_days,notes,updated_at)
                        VALUES (?,?,?,?,?,?,?)
                        ON CONFLICT(product_id) DO UPDATE SET
                          monthly_usage_kg=excluded.monthly_usage_kg,
                          safety_stock_days=excluded.safety_stock_days,
                          lead_time_days=excluded.lead_time_days,
                          reorder_review_days=excluded.reorder_review_days,
                          notes=excluded.notes,
                          updated_at=excluded.updated_at""",
                        (pid,float(monthly_new),int(safety_new),int(lead_new),int(review_new),
                         pnotes_new,datetime.now().isoformat(timespec="seconds")))
                    st.success("Stok politikası kaydedildi.")
                    st.rerun()

        with warehouse_tab:
            wh_df=query_df("""
                SELECT id,name AS depo,warehouse_type AS tip,city AS şehir,
                       CASE WHEN active=1 THEN 'Aktif' ELSE 'Pasif' END AS durum,notes AS notlar
                FROM warehouses ORDER BY name
            """)
            st.dataframe(wh_df,use_container_width=True,hide_index=True)
            with st.form("proc_new_warehouse",clear_on_submit=True):
                w1,w2=st.columns(2)
                wname=w1.text_input("Depo adı *")
                wtype=w2.selectbox("Tip",["Normal Depo","Antrepo / Bonded","Müşteri Konsinye","Diğer"])
                city=st.text_input("Şehir")
                notes=st.text_area("Not")
                if st.form_submit_button("Depo ekle") and wname.strip():
                    exists=int(query_df("SELECT COUNT(*) n FROM warehouses WHERE lower(name)=lower(?)",(wname.strip(),)).iloc[0]["n"])
                    if exists:
                        st.warning("Bu depo zaten var.")
                    else:
                        execute("INSERT INTO warehouses (name,warehouse_type,city,active,notes) VALUES (?,?,?,1,?)",
                                (wname.strip(),wtype,city,notes))
                        st.success("Depo eklendi.")
                        st.rerun()

    with finance_tab:
        st.markdown("### 💶 Finans + Tahsilat + Nakit Akışı")
        st.caption(
            "Alacak, borç, banka/kasa ve planlı nakit hareketlerini birleştirir. "
            "30/60/90 günlük nakit ihtiyacını seçilen yönetim para birimine göre gösterir."
        )

        cashflow_tab, ar_tab, ap_tab, accounts_tab, events_tab, finance_history_tab = st.tabs(
            ["📈 Nakit Tahmini","💰 Alacak / Tahsilat","💸 Borç / Ödeme","🏦 Banka & Kasa","🗓 Planlı Hareket","📚 İşlem Geçmişi"]
        )

        with cashflow_tab:
            base_currency_fin=st.selectbox(
                "Yönetim para birimi",
                ["EUR","USD","GBP","TRY"],
                index=0,
                key="fin_base_currency"
            )
            st.info(
                "Not: Çok para birimli tahminde her kayıt için girilen 'yönetim kuruna' göre hesap yapılır. "
                "Kur değişirse ilgili kayıt veya hesap kurunu güncellemek gerekir."
            )

            accounts_all=query_df("""
                SELECT name,account_type,currency,balance,fx_to_base,base_currency,
                       balance*fx_to_base AS base_value
                FROM cash_accounts WHERE active=1 ORDER BY name
            """)
            rec_all=outstanding_receivables()
            pay_all=outstanding_payables()
            if not rec_all.empty:
                rec_all=rec_all[rec_all["base_currency"]==base_currency_fin].copy()
            if not pay_all.empty:
                pay_all=pay_all[pay_all["base_currency"]==base_currency_fin].copy()
            cash_total=cash_position_base(base_currency_fin)
            rec_total=float(rec_all["outstanding_base"].sum()) if not rec_all.empty else 0.0
            overdue_total=float(rec_all.loc[rec_all["days_overdue"]>0,"outstanding_base"].sum()) if not rec_all.empty else 0.0
            pay_total=float(pay_all["outstanding_base"].sum()) if not pay_all.empty else 0.0

            f1,f2,f3,f4=st.columns(4)
            f1.metric("Nakit / banka",f"{cash_total:,.0f} {base_currency_fin}")
            f2.metric("Açık alacak",f"{rec_total:,.0f} {base_currency_fin}")
            f3.metric("Gecikmiş alacak",f"{overdue_total:,.0f} {base_currency_fin}")
            f4.metric("Açık borç",f"{pay_total:,.0f} {base_currency_fin}")

            forecast=cash_forecast(base_currency_fin,(7,30,60,90))
            st.markdown("#### Nakit projeksiyonu")
            st.dataframe(forecast,use_container_width=True,hide_index=True)

            if not forecast.empty:
                ninety=float(forecast.loc[forecast["Gün"]==90,"Tahmini Nakit"].iloc[0])
                min_cash=float(forecast["Tahmini Nakit"].min())
                if min_cash < 0:
                    st.error(
                        f"Mevcut kayıtlara göre dönem içinde yaklaşık {abs(min_cash):,.0f} "
                        f"{base_currency_fin} finansman açığı oluşabilir."
                    )
                else:
                    st.success(
                        f"Mevcut kayıtlara göre 90 günlük tahmini nakit "
                        f"{ninety:,.0f} {base_currency_fin}."
                    )

            st.markdown("#### Gecikmiş müşteri alacakları")
            if rec_all.empty:
                st.info("Açık alacak yok.")
            else:
                overdue_view=rec_all[rec_all["days_overdue"]>0].copy()
                if overdue_view.empty:
                    st.success("Vadesi geçmiş müşteri alacağı yok.")
                else:
                    st.dataframe(
                        overdue_view[
                            ["id","customer","invoice_no","due_date","outstanding",
                             "currency","days_overdue","outstanding_base","risk"]
                        ],
                        use_container_width=True,hide_index=True
                    )

        with ar_tab:
            rec=outstanding_receivables()
            st.markdown("#### Açık müşteri alacakları")
            if rec.empty:
                st.info("Açık alacak yok.")
            else:
                ar_view=rec.rename(columns={
                    "customer":"müşteri","invoice_no":"fatura","due_date":"vade",
                    "outstanding":"kalan","days_overdue":"gecikme_gün",
                    "outstanding_base":"yönetim_tutarı","risk":"risk"
                })
                st.dataframe(
                    ar_view[["id","müşteri","fatura","vade","kalan","currency",
                             "gecikme_gün","yönetim_tutarı","base_currency","risk"]],
                    use_container_width=True,hide_index=True
                )

            ar1,ar2=st.tabs(["Yeni Alacak","Tahsilat Gir"])
            with ar1:
                customers_ar=query_df("SELECT id,name,default_payment_days FROM customers ORDER BY name")
                opps_ar=query_df("""
                    SELECT o.id,o.customer_id,o.product,o.stage
                    FROM opportunities o
                    WHERE o.stage NOT IN ('Kaybedildi')
                    ORDER BY o.id DESC
                """)
                if customers_ar.empty:
                    st.info("Önce müşteri ekleyin.")
                else:
                    with st.form("fin_new_receivable",clear_on_submit=True):
                        customer_name=st.selectbox("Müşteri",customers_ar["name"].tolist())
                        cr=customers_ar[customers_ar["name"]==customer_name].iloc[0]
                        customer_id=int(cr["id"])
                        invoice_no=st.text_input("Fatura / belge no")
                        r1,r2,r3=st.columns(3)
                        invoice_date=r1.date_input("Fatura tarihi",value=date.today())
                        default_days=int(cr["default_payment_days"] or 90)
                        due_date=r2.date_input("Vade",value=date.today()+timedelta(days=default_days))
                        amount=r3.number_input("Tutar",min_value=0.0,value=0.0,step=1000.0)
                        r4,r5,r6=st.columns(3)
                        currency=r4.selectbox("Para",["EUR","USD","GBP","TRY"],key="fin_ar_currency")
                        base_currency=r5.selectbox("Yönetim para",["EUR","USD","GBP","TRY"],key="fin_ar_base")
                        fx=r6.number_input(f"1 {currency} = kaç yönetim para?",min_value=0.0001,value=1.0,step=0.01,format="%.4f")
                        customer_opps=opps_ar[opps_ar["customer_id"]==customer_id]
                        labels=["— Fırsata bağlama —"]; omap={"— Fırsata bağlama —":None}
                        for _,orow in customer_opps.iterrows():
                            label=f"#{int(orow['id'])} · {orow['product']} · {orow['stage']}"
                            labels.append(label); omap[label]=int(orow["id"])
                        opp_label=st.selectbox("Satış fırsatı",labels)
                        notes=st.text_area("Not")
                        if st.form_submit_button("Alacağı kaydet",type="primary"):
                            if amount<=0:
                                st.error("Tutar sıfırdan büyük olmalı.")
                            else:
                                execute("""INSERT INTO receivables
                                    (customer_id,invoice_no,invoice_date,due_date,amount,paid_amount,
                                     currency,fx_to_base,base_currency,status,opportunity_id,notes)
                                    VALUES (?,?,?,?,?,0,?,?,?,'Açık',?,?)""",
                                    (customer_id,invoice_no,str(invoice_date),str(due_date),float(amount),
                                     currency,float(fx),base_currency,omap[opp_label],notes))
                                st.success("Alacak kaydedildi.")
                                st.rerun()

            with ar2:
                rec_now=outstanding_receivables()
                accounts=query_df("SELECT id,name,currency FROM cash_accounts WHERE active=1 ORDER BY name")
                if rec_now.empty:
                    st.info("Tahsil edilecek açık alacak yok.")
                else:
                    rid=st.selectbox(
                        "Alacak",
                        rec_now["id"].tolist(),
                        format_func=lambda x:f"#{x} · {rec_now.loc[rec_now['id']==x,'customer'].iloc[0]} · {rec_now.loc[rec_now['id']==x,'outstanding'].iloc[0]:,.2f} {rec_now.loc[rec_now['id']==x,'currency'].iloc[0]}",
                        key="fin_ar_pay_select"
                    )
                    rr=rec_now[rec_now["id"]==rid].iloc[0]
                    if not accounts.empty:
                        accounts=accounts[accounts["currency"]==rr["currency"]].copy()
                    t1,t2=st.columns(2)
                    collection=t1.number_input("Tahsilat",min_value=0.0,max_value=float(rr["outstanding"]),value=float(rr["outstanding"]),step=100.0,key="fin_ar_collect_amount")
                    collection_date=t2.date_input("Tahsilat tarihi",value=date.today(),key="fin_ar_collect_date")
                    account_map={"— Hesaba bağlama —":None}
                    if not accounts.empty:
                        for _,a in accounts.iterrows():
                            account_map[f"{a['name']} · {a['currency']}"]=int(a["id"])
                    account_label=st.selectbox("Girdiği banka/kasa",list(account_map.keys()),key="fin_ar_account")
                    reference=st.text_input("Referans",key="fin_ar_reference")
                    notes=st.text_input("Tahsilat notu",key="fin_ar_collect_notes")
                    if st.button("Tahsilatı kaydet",type="primary",use_container_width=True,key="fin_ar_collect_btn"):
                        ok,msg=record_receivable_payment(
                            rid,collection,collection_date,account_map[account_label],reference,notes
                        )
                        (st.success if ok else st.warning)(msg)
                        if ok: st.rerun()

        with ap_tab:
            pay=outstanding_payables()
            st.markdown("#### Açık tedarikçi borçları")
            if pay.empty:
                st.info("Açık tedarikçi borcu yok.")
            else:
                ap_view=pay.rename(columns={
                    "supplier":"tedarikçi","invoice_no":"fatura","due_date":"vade",
                    "outstanding":"kalan","days_overdue":"gecikme_gün",
                    "outstanding_base":"yönetim_tutarı","risk":"risk"
                })
                st.dataframe(
                    ap_view[["id","tedarikçi","fatura","vade","kalan","currency",
                             "gecikme_gün","yönetim_tutarı","base_currency","risk"]],
                    use_container_width=True,hide_index=True
                )

            ap1,ap2=st.tabs(["Yeni Borç","Ödeme Gir"])
            with ap1:
                open_pos=query_df("""
                    SELECT id,po_number,supplier,product_name,quantity_kg,unit_price,currency
                    FROM purchase_orders
                    WHERE status!='İptal'
                    ORDER BY id DESC
                """)
                with st.form("fin_new_payable",clear_on_submit=True):
                    po_labels=["— PO'ya bağlama —"]; pmap={"— PO'ya bağlama —":None}
                    for _,p in open_pos.iterrows():
                        label=f"{p['po_number']} · {p['supplier']} · {p['product_name']}"
                        po_labels.append(label); pmap[label]=int(p["id"])
                    po_label=st.selectbox("PO",po_labels)
                    selected_po=None
                    if pmap[po_label]:
                        selected_po=open_pos[open_pos["id"]==pmap[po_label]].iloc[0]
                    supplier=st.text_input("Tedarikçi *",value=str(selected_po["supplier"] if selected_po is not None else ""))
                    invoice_no=st.text_input("Fatura / belge no",key="fin_ap_invoice")
                    p1,p2,p3=st.columns(3)
                    invoice_date=p1.date_input("Fatura tarihi",value=date.today(),key="fin_ap_invoice_date")
                    due_date=p2.date_input("Vade",value=date.today()+timedelta(days=30),key="fin_ap_due")
                    default_amount=(float(selected_po["quantity_kg"])*float(selected_po["unit_price"])) if selected_po is not None else 0.0
                    amount=p3.number_input("Tutar",min_value=0.0,value=float(default_amount),step=1000.0,key="fin_ap_amount")
                    p4,p5,p6=st.columns(3)
                    default_cur=str(selected_po["currency"] if selected_po is not None else "EUR")
                    cur_list=["EUR","USD","GBP","TRY"]
                    currency=p4.selectbox("Para",cur_list,index=cur_list.index(default_cur if default_cur in cur_list else "EUR"),key="fin_ap_currency")
                    base_currency=p5.selectbox("Yönetim para",cur_list,key="fin_ap_base")
                    fx=p6.number_input(f"1 {currency} = kaç yönetim para?",min_value=0.0001,value=1.0,step=0.01,format="%.4f",key="fin_ap_fx")
                    notes=st.text_area("Not",key="fin_ap_notes")
                    if st.form_submit_button("Borcu kaydet",type="primary"):
                        if not supplier.strip() or amount<=0:
                            st.error("Tedarikçi ve pozitif tutar gerekli.")
                        else:
                            execute("""INSERT INTO payables
                                (supplier,purchase_order_id,invoice_no,invoice_date,due_date,
                                 amount,paid_amount,currency,fx_to_base,base_currency,status,notes)
                                VALUES (?,?,?,?,?,?,0,?,?,?,'Açık',?)""",
                                (supplier.strip(),pmap[po_label],invoice_no,str(invoice_date),str(due_date),
                                 float(amount),currency,float(fx),base_currency,notes))
                            st.success("Borç kaydedildi.")
                            st.rerun()

            with ap2:
                pay_now=outstanding_payables()
                accounts=query_df("SELECT id,name,currency FROM cash_accounts WHERE active=1 ORDER BY name")
                if pay_now.empty:
                    st.info("Ödenecek açık borç yok.")
                else:
                    pid=st.selectbox(
                        "Borç",
                        pay_now["id"].tolist(),
                        format_func=lambda x:f"#{x} · {pay_now.loc[pay_now['id']==x,'supplier'].iloc[0]} · {pay_now.loc[pay_now['id']==x,'outstanding'].iloc[0]:,.2f} {pay_now.loc[pay_now['id']==x,'currency'].iloc[0]}",
                        key="fin_ap_pay_select"
                    )
                    pp=pay_now[pay_now["id"]==pid].iloc[0]
                    if not accounts.empty:
                        accounts=accounts[accounts["currency"]==pp["currency"]].copy()
                    q1,q2=st.columns(2)
                    payment=q1.number_input("Ödeme",min_value=0.0,max_value=float(pp["outstanding"]),value=float(pp["outstanding"]),step=100.0,key="fin_ap_pay_amount")
                    payment_date=q2.date_input("Ödeme tarihi",value=date.today(),key="fin_ap_pay_date")
                    account_map={"— Hesaba bağlama —":None}
                    if not accounts.empty:
                        for _,a in accounts.iterrows():
                            account_map[f"{a['name']} · {a['currency']}"]=int(a["id"])
                    account_label=st.selectbox("Çıktığı banka/kasa",list(account_map.keys()),key="fin_ap_account")
                    reference=st.text_input("Referans",key="fin_ap_reference")
                    notes=st.text_input("Ödeme notu",key="fin_ap_pay_notes")
                    if st.button("Ödemeyi kaydet",type="primary",use_container_width=True,key="fin_ap_pay_btn"):
                        ok,msg=record_payable_payment(
                            pid,payment,payment_date,account_map[account_label],reference,notes
                        )
                        (st.success if ok else st.warning)(msg)
                        if ok: st.rerun()

        with accounts_tab:
            account_df=query_df("""
                SELECT id,name AS hesap,account_type AS tip,currency AS para,
                       balance AS bakiye,fx_to_base AS yönetim_kuru,
                       base_currency AS yönetim_para,
                       balance*fx_to_base AS yönetim_değeri,notes AS notlar
                FROM cash_accounts WHERE active=1 ORDER BY name
            """)
            st.dataframe(account_df,use_container_width=True,hide_index=True)
            with st.form("fin_new_account",clear_on_submit=True):
                a1,a2=st.columns(2)
                name=a1.text_input("Hesap adı *",placeholder="EUR Banka / GBP Banka / Kasa")
                account_type=a2.selectbox("Tip",["Banka","Kasa","Kredi / Overdraft","Diğer"])
                a3,a4,a5=st.columns(3)
                currency=a3.selectbox("Para",["EUR","USD","GBP","TRY"],key="fin_acc_currency")
                balance=a4.number_input("Bakiye",value=0.0,step=1000.0,key="fin_acc_balance")
                fx=a5.number_input("Yönetim kuru",min_value=0.0001,value=1.0,step=0.01,format="%.4f",key="fin_acc_fx")
                base_currency=st.selectbox("Yönetim para",["EUR","USD","GBP","TRY"],key="fin_acc_base")
                notes=st.text_input("Not",key="fin_acc_notes")
                if st.form_submit_button("Hesap ekle",type="primary") and name.strip():
                    exists=int(query_df("SELECT COUNT(*) n FROM cash_accounts WHERE lower(name)=lower(?)",(name.strip(),)).iloc[0]["n"])
                    if exists:
                        st.warning("Bu hesap zaten var.")
                    else:
                        execute("""INSERT INTO cash_accounts
                            (name,currency,balance,fx_to_base,base_currency,account_type,active,notes,updated_at)
                            VALUES (?,?,?,?,?,?,1,?,?)""",
                            (name.strip(),currency,float(balance),float(fx),base_currency,account_type,
                             notes,datetime.now().isoformat(timespec="seconds")))
                        st.success("Hesap eklendi.")
                        st.rerun()

            if not account_df.empty:
                acc_id=st.selectbox(
                    "Bakiye / kur güncellenecek hesap",
                    account_df["id"].tolist(),
                    format_func=lambda x:f"{account_df.loc[account_df['id']==x,'hesap'].iloc[0]} · {account_df.loc[account_df['id']==x,'para'].iloc[0]}",
                    key="fin_account_edit"
                )
                acc=query_df("SELECT * FROM cash_accounts WHERE id=?",(int(acc_id),)).iloc[0]
                a6,a7=st.columns(2)
                new_balance=a6.number_input("Yeni bakiye",value=float(acc["balance"] or 0),step=1000.0,key="fin_new_balance")
                new_fx=a7.number_input("Yeni yönetim kuru",min_value=0.0001,value=float(acc["fx_to_base"] or 1),step=0.01,format="%.4f",key="fin_new_fx")
                if st.button("Hesabı güncelle",key="fin_update_account"):
                    execute("UPDATE cash_accounts SET balance=?,fx_to_base=?,updated_at=? WHERE id=?",
                            (float(new_balance),float(new_fx),datetime.now().isoformat(timespec="seconds"),int(acc_id)))
                    st.success("Hesap güncellendi.")
                    st.rerun()

        with events_tab:
            events=query_df("""
                SELECT id,event_date AS tarih,direction AS yön,category AS kategori,
                       description AS açıklama,amount AS tutar,currency AS para,
                       fx_to_base AS yönetim_kuru,base_currency AS yönetim_para,status AS durum
                FROM cash_events
                ORDER BY event_date ASC,id ASC
            """)
            st.dataframe(events,use_container_width=True,hide_index=True)
            with st.form("fin_new_event",clear_on_submit=True):
                e1,e2,e3=st.columns(3)
                event_date=e1.date_input("Tarih",value=date.today()+timedelta(days=7))
                direction=e2.selectbox("Yön",["Giriş","Çıkış"])
                category=e3.selectbox("Kategori",["Vergi","Maaş","Kira","Kredi","Sermaye","Yatırım","Diğer"])
                description=st.text_input("Açıklama *")
                e4,e5,e6=st.columns(3)
                amount=e4.number_input("Tutar",min_value=0.0,value=0.0,step=1000.0)
                currency=e5.selectbox("Para",["EUR","USD","GBP","TRY"],key="fin_event_cur")
                base_currency=e6.selectbox("Yönetim para",["EUR","USD","GBP","TRY"],key="fin_event_base")
                fx=st.number_input("Yönetim kuru",min_value=0.0001,value=1.0,step=0.01,format="%.4f",key="fin_event_fx")
                notes=st.text_area("Not",key="fin_event_notes")
                if st.form_submit_button("Planlı hareket ekle",type="primary") and description.strip() and amount>0:
                    execute("""INSERT INTO cash_events
                        (event_date,direction,category,description,amount,currency,fx_to_base,
                         base_currency,status,notes)
                        VALUES (?,?,?,?,?,?,?,?,'Planlı',?)""",
                        (str(event_date),direction,category,description.strip(),float(amount),
                         currency,float(fx),base_currency,notes))
                    st.success("Planlı nakit hareketi eklendi.")
                    st.rerun()

        with finance_history_tab:
            tx=query_df("""
                SELECT ft.id,ft.transaction_date AS tarih,ft.transaction_type AS tip,
                       CASE WHEN ft.receivable_id IS NOT NULL THEN c.name ELSE p.supplier END AS taraf,
                       ft.amount AS tutar,ft.currency AS para,ca.name AS hesap,
                       ft.reference AS referans,ft.notes AS notlar
                FROM finance_transactions ft
                LEFT JOIN receivables r ON r.id=ft.receivable_id
                LEFT JOIN customers c ON c.id=r.customer_id
                LEFT JOIN payables p ON p.id=ft.payable_id
                LEFT JOIN cash_accounts ca ON ca.id=ft.account_id
                ORDER BY ft.transaction_date DESC,ft.id DESC
            """)
            st.dataframe(tx,use_container_width=True,hide_index=True)

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

        st.markdown("#### Finans / tahsilat uyarıları")
        ceo_rec=outstanding_receivables()
        ceo_pay=outstanding_payables()
        if not ceo_rec.empty:
            ceo_rec=ceo_rec[ceo_rec["base_currency"]=="EUR"].copy()
        if not ceo_pay.empty:
            ceo_pay=ceo_pay[ceo_pay["base_currency"]=="EUR"].copy()
        ceo_cash=cash_position_base("EUR")
        ceo_rec_total=float(ceo_rec["outstanding_base"].sum()) if not ceo_rec.empty else 0.0
        ceo_overdue=float(ceo_rec.loc[ceo_rec["days_overdue"]>0,"outstanding_base"].sum()) if not ceo_rec.empty else 0.0
        ceo_pay_total=float(ceo_pay["outstanding_base"].sum()) if not ceo_pay.empty else 0.0
        fc90=cash_forecast("EUR",(30,60,90))
        z1,z2,z3,z4=st.columns(4)
        z1.metric("Nakit",f"{ceo_cash:,.0f} EUR")
        z2.metric("Açık alacak",f"{ceo_rec_total:,.0f} EUR")
        z3.metric("Gecikmiş alacak",f"{ceo_overdue:,.0f} EUR")
        z4.metric("Açık borç",f"{ceo_pay_total:,.0f} EUR")
        if not fc90.empty:
            st.dataframe(fc90,use_container_width=True,hide_index=True)
            min_cash=float(fc90["Tahmini Nakit"].min())
            if min_cash<0:
                st.error(f"30/60/90 günlük projeksiyonda yaklaşık {abs(min_cash):,.0f} EUR nakit açığı riski var.")
        if not ceo_rec.empty:
            risky=ceo_rec[ceo_rec["days_overdue"]>0].copy()
            if not risky.empty:
                st.markdown("##### Gecikmiş tahsilatlar")
                st.dataframe(
                    risky[["customer","invoice_no","due_date","outstanding","currency","days_overdue","risk"]].head(10),
                    use_container_width=True,hide_index=True
                )

        st.markdown("#### Satın alma / stok uyarıları")
        ceo_stock=stock_snapshot()
        if ceo_stock.empty:
            st.info("Henüz stok politikası / stok verisi yok.")
        else:
            ceo_alerts=ceo_stock[ceo_stock["status"]!="OK"].copy()
            if ceo_alerts.empty:
                st.success("Kritik stok / yeniden sipariş uyarısı yok.")
            else:
                ceo_alerts=ceo_alerts.rename(columns={
                    "name":"ürün","net_available_kg":"net_stok_kg","inbound_kg":"yolda_kg",
                    "stock_days":"stok_gün","suggested_order_kg":"önerilen_sipariş_kg","status":"durum"
                })
                st.dataframe(
                    ceo_alerts[["ürün","net_stok_kg","yolda_kg","stok_gün",
                                "önerilen_sipariş_kg","durum"]].head(10),
                    use_container_width=True,hide_index=True
                )

        st.markdown("#### Yaklaşan sevkiyatlar")
        ceo_ship=query_df("""
            SELECT po.product_name AS ürün,po.supplier AS tedarikçi,
                   s.quantity_kg/1000.0 AS ton,s.eta,
                   s.status AS durum,w.name AS depo
            FROM shipments s
            JOIN purchase_orders po ON po.id=s.purchase_order_id
            LEFT JOIN warehouses w ON w.id=s.destination_warehouse_id
            WHERE s.received_to_stock=0 AND s.status!='İptal'
            ORDER BY CASE WHEN s.eta='' THEN 1 ELSE 0 END,s.eta ASC
            LIMIT 8
        """)
        if not ceo_ship.empty:
            st.dataframe(ceo_ship,use_container_width=True,hide_index=True)

        st.markdown("#### Teklif kârlılığı")
        recent_quotes = query_df("""
            SELECT q.id, c.name AS müşteri, q.product_name AS ürün,
                   q.sell_price_per_kg AS satış_fiyatı,
                   q.total_cost_per_kg AS gerçek_maliyet,
                   q.profit_per_kg AS katkı_kg, q.margin_pct AS marj,
                   q.profit_total_base AS toplam_katkı,
                   q.base_currency AS para, q.status AS durum
            FROM quotes q
            LEFT JOIN customers c ON c.id=q.customer_id
            ORDER BY q.id DESC
            LIMIT 8
        """)
        if recent_quotes.empty:
            st.info("Henüz kayıtlı teklif hesabı yok.")
        else:
            st.dataframe(recent_quotes, use_container_width=True, hide_index=True)

        st.markdown("#### Henüz açılmamış en güçlü ürün fırsatları")
        ceo_recs = recommendation_rows()
        if ceo_recs.empty:
            st.info("Yeni cross-sell önerisi yok.")
        else:
            st.dataframe(
                ceo_recs[
                    ["Müşteri","Ürün","Fit Score","Neden","Sorumlu"]
                ].head(10),
                use_container_width=True,
                hide_index=True,
                column_config={
                    "Fit Score": st.column_config.ProgressColumn(
                        "Fit Score", min_value=0, max_value=100
                    )
                },
            )

        st.markdown("#### Yönetici uyarısı")
        if overdue or stale_count or critical:
            st.warning(
                f"{critical} kritik/yüksek görev, {overdue} geciken satış takibi ve "
                f"{stale_count} uzun süredir temas edilmeyen aktif fırsat var."
            )
        else:
            st.success("Şu anda kritik gecikmiş satış takibi görünmüyor.")
