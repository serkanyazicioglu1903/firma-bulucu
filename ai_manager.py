import sqlite3
from datetime import date
from pathlib import Path

import pandas as pd
import streamlit as st


def connect(db_path):
    conn = sqlite3.connect(Path(db_path), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


def query_df(db_path, sql, params=()):
    with connect(db_path) as conn:
        return pd.read_sql_query(sql, conn, params=params)


def scalar(db_path, sql, params=(), default=0):
    df = query_df(db_path, sql, params)
    if df.empty:
        return default
    return df.iloc[0, 0]


def _money(v, currency="EUR"):
    try:
        return f"{float(v):,.0f} {currency}"
    except Exception:
        return f"0 {currency}"


def dashboard_snapshot(db_path):
    active_opps = int(scalar(
        db_path,
        "SELECT COUNT(*) FROM opportunities WHERE stage NOT IN ('Kazanıldı','Kaybedildi')"
    ))
    weighted = float(scalar(
        db_path,
        """SELECT COALESCE(SUM(value*probability/100.0),0)
           FROM opportunities WHERE stage!='Kaybedildi'"""
    ))
    overdue_tasks = int(scalar(
        db_path,
        """SELECT COUNT(*) FROM tasks
           WHERE status!='Tamamlandı' AND due_date!='' AND due_date < ?""",
        (str(date.today()),)
    ))
    overdue_followups = int(scalar(
        db_path,
        """SELECT COUNT(*) FROM opportunities
           WHERE stage NOT IN ('Kazanıldı','Kaybedildi')
             AND due_date!='' AND due_date < ?""",
        (str(date.today()),)
    ))
    open_quality = int(scalar(
        db_path,
        """SELECT COUNT(*) FROM quality_cases
           WHERE status NOT IN ('Kapandı','İptal')"""
    ))
    overdue_ar = float(scalar(
        db_path,
        """SELECT COALESCE(SUM((amount-paid_amount)*fx_to_base),0)
           FROM receivables
           WHERE status!='İptal' AND amount-paid_amount>0
             AND due_date!='' AND due_date < ? AND base_currency='EUR'""",
        (str(date.today()),)
    ))
    return {
        "active_opps": active_opps,
        "weighted": weighted,
        "overdue_tasks": overdue_tasks,
        "overdue_followups": overdue_followups,
        "open_quality": open_quality,
        "overdue_ar": overdue_ar,
    }


def top_priorities(db_path, limit=10):
    rows = []

    tasks = query_df(db_path, """
        SELECT title,related_to,owner,priority,due_date
        FROM tasks
        WHERE status!='Tamamlandı'
        ORDER BY CASE priority
          WHEN 'Kritik' THEN 1 WHEN 'Yüksek' THEN 2
          WHEN 'Orta' THEN 3 ELSE 4 END,
          CASE WHEN due_date='' THEN 1 ELSE 0 END,
          due_date ASC
        LIMIT ?
    """, (limit,))
    for _, r in tasks.iterrows():
        score = {"Kritik": 100, "Yüksek": 80, "Orta": 60, "Düşük": 40}.get(r["priority"], 50)
        if r["due_date"] and str(r["due_date"]) < str(date.today()):
            score += 20
        rows.append({
            "Skor": min(score, 120),
            "Tür": "Görev",
            "Konu": r["title"],
            "İlgili": r["related_to"],
            "Sorumlu": r["owner"],
            "Tarih": r["due_date"],
        })

    opps = query_df(db_path, """
        SELECT c.name AS customer,o.product,o.stage,o.value,o.currency,
               o.probability,o.next_action,o.due_date,o.owner
        FROM opportunities o
        LEFT JOIN customers c ON c.id=o.customer_id
        WHERE o.stage NOT IN ('Kazanıldı','Kaybedildi')
        ORDER BY o.value DESC
        LIMIT ?
    """, (limit,))
    for _, r in opps.iterrows():
        score = 50
        if r["stage"] in ("Pazarlık","Teklif","Problem / Koruma"):
            score += 25
        if r["due_date"] and str(r["due_date"]) < str(date.today()):
            score += 20
        if float(r["value"] or 0) >= 250000:
            score += 15
        rows.append({
            "Skor": min(score, 120),
            "Tür": "Satış",
            "Konu": f"{r['product']} · {r['stage']}",
            "İlgili": r["customer"] or "",
            "Sorumlu": r["owner"],
            "Tarih": r["due_date"],
        })

    quality = query_df(db_path, """
        SELECT case_no,product_name,severity,status,owner,target_close_date
        FROM quality_cases
        WHERE status NOT IN ('Kapandı','İptal')
        ORDER BY CASE severity WHEN 'Kritik' THEN 1 WHEN 'Yüksek' THEN 2 ELSE 3 END,
                 target_close_date ASC
        LIMIT ?
    """, (limit,))
    for _, r in quality.iterrows():
        score = 95 if r["severity"] == "Kritik" else 80 if r["severity"] == "Yüksek" else 65
        if r["target_close_date"] and str(r["target_close_date"]) < str(date.today()):
            score += 20
        rows.append({
            "Skor": min(score, 120),
            "Tür": "Kalite",
            "Konu": f"{r['case_no']} · {r['product_name']} · {r['status']}",
            "İlgili": "",
            "Sorumlu": r["owner"],
            "Tarih": r["target_close_date"],
        })

    if not rows:
        return pd.DataFrame()
    return pd.DataFrame(rows).sort_values(["Skor","Tarih"], ascending=[False, True]).head(limit)


def sales_risks(db_path):
    return query_df(db_path, """
        SELECT c.name AS müşteri,o.product AS ürün,o.stage AS aşama,
               o.value AS değer,o.currency AS para,o.probability AS olasılık,
               o.next_action AS sonraki_aksiyon,o.due_date AS takip_tarihi,
               o.last_contact_date AS son_görüşme,o.owner AS sorumlu
        FROM opportunities o
        LEFT JOIN customers c ON c.id=o.customer_id
        WHERE o.stage NOT IN ('Kazanıldı','Kaybedildi')
          AND (
            o.stage='Problem / Koruma'
            OR (o.due_date!='' AND o.due_date < date('now'))
            OR o.last_contact_date=''
            OR julianday(date('now'))-julianday(o.last_contact_date)>=14
          )
        ORDER BY o.value DESC
        LIMIT 20
    """)


def cash_risks(db_path):
    return query_df(db_path, """
        SELECT c.name AS müşteri,r.invoice_no AS fatura,r.due_date AS vade,
               r.amount-r.paid_amount AS kalan,r.currency AS para,
               CAST(julianday(date('now'))-julianday(r.due_date) AS INTEGER) AS gecikme_gün
        FROM receivables r
        JOIN customers c ON c.id=r.customer_id
        WHERE r.status!='İptal' AND r.amount-r.paid_amount>0
          AND r.due_date!='' AND r.due_date < date('now')
        ORDER BY gecikme_gün DESC,kalan DESC
        LIMIT 20
    """)


def stock_risks(db_path):
    return query_df(db_path, """
        WITH stock AS (
          SELECT p.id,p.name,p.supplier,
                 COALESCE(SUM(CASE WHEN COALESCE(il.quality_status,'Released')='Released'
                                   THEN il.quantity_available_kg-il.quantity_reserved_kg ELSE 0 END),0) AS net_kg,
                 COALESCE(pol.monthly_usage_kg,0) AS monthly_kg,
                 COALESCE(pol.safety_stock_days,30) AS safety_days,
                 COALESCE(pol.lead_time_days,45) AS lead_days
          FROM product_catalog p
          LEFT JOIN inventory_lots il ON il.product_id=p.id
          LEFT JOIN inventory_policy pol ON pol.product_id=p.id
          WHERE p.active=1
          GROUP BY p.id,p.name,p.supplier,pol.monthly_usage_kg,pol.safety_stock_days,pol.lead_time_days
        )
        SELECT name AS ürün,supplier AS tedarikçi,net_kg AS net_stok_kg,
               monthly_kg AS aylık_tüketim_kg,
               CASE WHEN monthly_kg>0 THEN ROUND(net_kg/(monthly_kg/30.0),1) END AS stok_gün,
               safety_days AS güvenlik_gün,lead_days AS termin_gün
        FROM stock
        WHERE monthly_kg>0 AND net_kg/(monthly_kg/30.0) < (safety_days+lead_days)
        ORDER BY stok_gün ASC
        LIMIT 20
    """)


def margin_risks(db_path):
    return query_df(db_path, """
        SELECT q.id,c.name AS müşteri,q.product_name AS ürün,
               q.sell_price_per_kg AS satış,q.total_cost_per_kg AS gerçek_maliyet,
               q.margin_pct AS marj,q.target_margin_pct AS hedef_marj,
               q.profit_total_base AS toplam_katkı,q.base_currency AS para,
               q.status AS durum,q.created_at AS tarih
        FROM quotes q
        LEFT JOIN customers c ON c.id=q.customer_id
        WHERE q.profit_total_base<0 OR q.margin_pct<q.target_margin_pct
        ORDER BY q.created_at DESC
        LIMIT 20
    """)


def quality_risks(db_path):
    return query_df(db_path, """
        SELECT q.case_no AS dosya,q.product_name AS ürün,c.name AS müşteri,
               q.severity AS önem,q.status AS durum,
               q.affected_quantity_kg AS etkilenen_kg,
               q.estimated_loss AS tahmini_zarar,q.currency AS para,
               q.owner AS sorumlu,q.target_close_date AS hedef_kapanış
        FROM quality_cases q
        LEFT JOIN customers c ON c.id=q.customer_id
        WHERE q.status NOT IN ('Kapandı','İptal')
        ORDER BY CASE q.severity WHEN 'Kritik' THEN 1 WHEN 'Yüksek' THEN 2 ELSE 3 END,
                 q.target_close_date ASC
        LIMIT 20
    """)


def opportunities(db_path):
    return query_df(db_path, """
        SELECT c.name AS müşteri,o.product AS ürün,o.stage AS aşama,
               o.value AS değer,o.currency AS para,o.probability AS olasılık,
               ROUND(o.value*o.probability/100.0,0) AS ağırlıklı_değer,
               o.next_action AS sonraki_aksiyon,o.due_date AS takip_tarihi,
               o.owner AS sorumlu
        FROM opportunities o
        LEFT JOIN customers c ON c.id=o.customer_id
        WHERE o.stage NOT IN ('Kazanıldı','Kaybedildi')
        ORDER BY ağırlıklı_değer DESC
        LIMIT 25
    """)


def forgotten_customers(db_path):
    return query_df(db_path, """
        SELECT c.name AS müşteri,c.sector AS sektör,c.owner AS sorumlu,
               MAX(a.activity_date) AS son_aktivite,
               CAST(julianday(date('now'))-julianday(MAX(a.activity_date)) AS INTEGER) AS sessiz_gün
        FROM customers c
        LEFT JOIN activities a ON a.customer_id=c.id
        WHERE c.status IN ('Aktif','Potansiyel','Riskli')
        GROUP BY c.id,c.name,c.sector,c.owner
        HAVING MAX(a.activity_date) IS NULL
            OR julianday(date('now'))-julianday(MAX(a.activity_date))>=30
        ORDER BY sessiz_gün DESC
        LIMIT 25
    """)


def data_quality_issues(db_path):
    checks = [
        (
            "Yüksek",
            "CRM",
            "Müşteri sektör bilgisi eksik",
            "SELECT COUNT(*) FROM customers WHERE trim(COALESCE(sector,''))=''",
            "Sektör bilgisini doldur; ürün eşleştirme kalitesi artar.",
        ),
        (
            "Yüksek",
            "CRM",
            "Müşteri üretim profili eksik",
            """SELECT COUNT(*) FROM customers
               WHERE status IN ('Aktif','Potansiyel','Riskli')
                 AND trim(COALESCE(product_profile,''))=''""",
            "Müşterinin ürettiği ürünleri ve kullandığı hammadde gruplarını yaz.",
        ),
        (
            "Orta",
            "CRM",
            "Kontak/e-posta bilgisi eksik",
            """SELECT COUNT(*) FROM customers
               WHERE status IN ('Aktif','Potansiyel','Riskli')
                 AND trim(COALESCE(contact_email,''))=''""",
            "En az bir satış/teknik kontak e-postası ekle.",
        ),
        (
            "Kritik",
            "Satış",
            "Aktif fırsatta sonraki aksiyon yok",
            """SELECT COUNT(*) FROM opportunities
               WHERE stage NOT IN ('Kazanıldı','Kaybedildi')
                 AND trim(COALESCE(next_action,''))=''""",
            "Her aktif fırsata net bir sonraki aksiyon tanımla.",
        ),
        (
            "Kritik",
            "Satış",
            "Aktif fırsatta takip tarihi yok",
            """SELECT COUNT(*) FROM opportunities
               WHERE stage NOT IN ('Kazanıldı','Kaybedildi')
                 AND trim(COALESCE(due_date,''))=''""",
            "Takip tarihini belirle; fırsatın unutulmasını engelle.",
        ),
        (
            "Orta",
            "Ürün",
            "Aktif üründe hedef sektör bilgisi eksik",
            """SELECT COUNT(*) FROM product_catalog
               WHERE active=1 AND trim(COALESCE(target_sectors,''))=''""",
            "Hedef sektör anahtarlarını ekle; satış zekâsı daha isabetli olur.",
        ),
        (
            "Orta",
            "Ürün",
            "Aktif üründe tedarikçi bilgisi eksik",
            """SELECT COUNT(*) FROM product_catalog
               WHERE active=1 AND trim(COALESCE(supplier,''))=''""",
            "Onaylı/aday tedarikçiyi ürün kartına bağla.",
        ),
        (
            "Orta",
            "Stok",
            "Stok politikası tanımlanmamış aktif ürün",
            """SELECT COUNT(*) FROM product_catalog p
               LEFT JOIN inventory_policy ip ON ip.product_id=p.id
               WHERE p.active=1 AND ip.id IS NULL""",
            "Aylık tüketim, safety stock ve lead time tanımla.",
        ),
    ]
    rows = []
    for severity, area, issue, sql, action in checks:
        count = int(scalar(db_path, sql, default=0) or 0)
        if count > 0:
            rows.append({
                "Önem": severity,
                "Alan": area,
                "Eksik / Risk": issue,
                "Kayıt": count,
                "Önerilen Aksiyon": action,
            })
    if not rows:
        return pd.DataFrame()
    order = {"Kritik": 1, "Yüksek": 2, "Orta": 3, "Düşük": 4}
    df = pd.DataFrame(rows)
    df["_order"] = df["Önem"].map(order).fillna(9)
    return df.sort_values(["_order","Kayıt"], ascending=[True,False]).drop(columns=["_order"])


def answer_question(db_path, question):
    q = (question or "").lower().strip()
    if not q:
        return "Bir soru yaz.", None

    if any(x in q for x in ["bugün", "ne yap", "öncelik", "müdahale"]):
        return "Bugün müdahale edilmesi gereken en önemli konular:", top_priorities(db_path, 12)
    if any(x in q for x in ["nakit", "tahsilat", "alacak", "gecikmiş ödeme"]):
        return "Vadesi geçmiş müşteri alacakları:", cash_risks(db_path)
    if any(x in q for x in ["stok", "sipariş ver", "mal kaldı", "kritik ürün"]):
        return "Stok/yeniden sipariş riski taşıyan ürünler:", stock_risks(db_path)
    if any(x in q for x in ["marj", "zarar", "kârlı", "karlı", "teklif"]):
        return "Hedef marjın altında veya zararda olan teklifler:", margin_risks(db_path)
    if any(x in q for x in ["kalite", "claim", "şikayet", "problem"]):
        return "Açık kalite/claim dosyaları:", quality_risks(db_path)
    if any(x in q for x in ["unut", "aranmadı", "takip edilmedi", "30 gün"]):
        return "Uzun süredir aktivite olmayan müşteriler:", forgotten_customers(db_path)
    if any(x in q for x in ["fırsat", "pipeline", "satış"]):
        return "En önemli aktif satış fırsatları:", opportunities(db_path)
    if any(x in q for x in ["veri kalitesi", "eksik veri", "hangi veri eksik", "veri eksik"]):
        return "Sistemin karar kalitesini düşüren eksik veriler:", data_quality_issues(db_path)
    if any(x in q for x in ["risk", "sorun", "tehlike"]):
        return "Satış tarafındaki başlıca riskler:", sales_risks(db_path)

    return (
        "Bu API'siz sürüm şu konuları anlayabiliyor: bugün/öncelik, nakit/tahsilat, "
        "stok/sipariş, marj/teklif, kalite/claim, unutulan müşteriler, satış fırsatları ve riskler.",
        None,
    )


def build_ceo_brief_text(db_path):
    s = dashboard_snapshot(db_path)
    priorities = top_priorities(db_path, 5)
    lines = [
        f"CEO ÖZETİ — {date.today().isoformat()}",
        "",
        f"Aktif fırsat: {s['active_opps']}",
        f"Ağırlıklı satış pipeline: {_money(s['weighted'])}",
        f"Geciken satış takibi: {s['overdue_followups']}",
        f"Geciken görev: {s['overdue_tasks']}",
        f"Açık kalite/claim dosyası: {s['open_quality']}",
        f"Gecikmiş alacak (EUR bazlı): {_money(s['overdue_ar'])}",
        "",
        "BUGÜN ÖNCELİK:",
    ]
    if priorities.empty:
        lines.append("- Kritik konu görünmüyor.")
    else:
        for _, r in priorities.iterrows():
            lines.append(
                f"- [{r['Tür']}] {r['Konu']} | {r['İlgili'] or '-'} | "
                f"Sorumlu: {r['Sorumlu'] or '-'} | Tarih: {r['Tarih'] or '-'}"
            )
    return "\n".join(lines)


def render_ai_manager(db_path):
    st.markdown("### 🤖 AI Yönetici")
    st.caption(
        "Bu sürüm şirket veritabanını API ücreti olmadan analiz eder. "
        "Dış yapay zekâ çağrısı yapmaz; veriye dayalı yönetici sorguları ve CEO özeti üretir."
    )

    snap = dashboard_snapshot(db_path)
    c1,c2,c3,c4,c5,c6 = st.columns(6)
    c1.metric("Aktif fırsat", snap["active_opps"])
    c2.metric("Ağırlıklı pipeline", _money(snap["weighted"]))
    c3.metric("Geciken takip", snap["overdue_followups"])
    c4.metric("Geciken görev", snap["overdue_tasks"])
    c5.metric("Açık kalite", snap["open_quality"])
    c6.metric("Gecikmiş alacak", _money(snap["overdue_ar"]))

    brief_tab, ask_tab, risks_tab = st.tabs(
        ["☀️ CEO Sabah Özeti", "💬 Yöneticiye Sor", "🚨 Risk Merkezi"]
    )

    with brief_tab:
        brief = build_ceo_brief_text(db_path)
        st.text_area("Bugünkü yönetici özeti", value=brief, height=360)
        st.markdown("#### Öncelik tablosu")
        p = top_priorities(db_path, 12)
        if p.empty:
            st.success("Kritik öncelik görünmüyor.")
        else:
            st.dataframe(p, use_container_width=True, hide_index=True)

    with ask_tab:
        examples = [
            "Bugün neye müdahale etmeliyim?",
            "Hangi tahsilatlar gecikti?",
            "Hangi ürünlerde sipariş vermeliyiz?",
            "Hangi teklifler hedef marjın altında?",
            "Açık kalite ve claim dosyaları neler?",
            "30 gündür takip etmediğimiz müşteriler kimler?",
            "En büyük satış fırsatlarımız hangileri?",
            "Satış tarafındaki en büyük riskler neler?",
            "Sistemde hangi kritik veriler eksik?",
        ]
        preset = st.selectbox("Hazır soru", ["— Kendim yazacağım —"] + examples)
        default_q = "" if preset == "— Kendim yazacağım —" else preset
        q = st.text_input("Yönetici sorusu", value=default_q, key="ai_manager_question")
        if st.button("Soruyu analiz et", type="primary", key="ai_manager_ask"):
            title, df = answer_question(db_path, q)
            st.session_state["ai_manager_answer_title"] = title
            st.session_state["ai_manager_answer_df"] = df

        if st.session_state.get("ai_manager_answer_title"):
            st.markdown(f"#### {st.session_state['ai_manager_answer_title']}")
            df = st.session_state.get("ai_manager_answer_df")
            if isinstance(df, pd.DataFrame):
                if df.empty:
                    st.info("Bu sorgu için kayıt bulunamadı.")
                else:
                    st.dataframe(df, use_container_width=True, hide_index=True)
            else:
                st.info(st.session_state["ai_manager_answer_title"])

    with risks_tab:
        r1,r2 = st.columns(2)
        with r1:
            st.markdown("#### Satış riski")
            df = sales_risks(db_path)
            st.dataframe(df, use_container_width=True, hide_index=True)
            st.markdown("#### Marj riski")
            df = margin_risks(db_path)
            st.dataframe(df, use_container_width=True, hide_index=True)
        with r2:
            st.markdown("#### Tahsilat riski")
            df = cash_risks(db_path)
            st.dataframe(df, use_container_width=True, hide_index=True)
            st.markdown("#### Kalite riski")
            df = quality_risks(db_path)
            st.dataframe(df, use_container_width=True, hide_index=True)

        st.markdown("#### Veri kalitesi")
        quality_df = data_quality_issues(db_path)
        if quality_df.empty:
            st.success("Karar motorunu etkileyen kritik veri eksiği görünmüyor.")
        else:
            st.caption(
                "Bu tablo satış zekâsı, stok tahmini ve yönetici raporlarının doğruluğunu "
                "doğrudan etkileyen eksik alanları gösterir."
            )
            st.dataframe(quality_df, use_container_width=True, hide_index=True)
