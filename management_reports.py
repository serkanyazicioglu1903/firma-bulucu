import sqlite3
from pathlib import Path

import pandas as pd
import streamlit as st


def connect(db_path):
    conn=sqlite3.connect(Path(db_path),check_same_thread=False)
    conn.row_factory=sqlite3.Row
    return conn


def query_df(db_path,sql,params=()):
    with connect(db_path) as conn:
        return pd.read_sql_query(sql,conn,params=params)


def render_management_reports(db_path):
    st.markdown("### 📈 Yönetim Raporları")
    st.caption("Satış, müşteri, ürün, görev ve kârlılık performansını tek ekranda toplar.")

    sales_tab, customer_tab, product_tab, team_tab = st.tabs(
        ["💰 Satış & Pipeline","👥 Müşteri","📦 Ürün","🧑‍💼 Ekip"]
    )

    with sales_tab:
        funnel=query_df(db_path,"""
            SELECT stage AS aşama,COUNT(*) AS fırsat_sayısı,
                   ROUND(SUM(value),0) AS toplam_değer,
                   ROUND(SUM(value*probability/100.0),0) AS ağırlıklı_değer
            FROM opportunities
            GROUP BY stage
            ORDER BY CASE stage
              WHEN 'Lead' THEN 1 WHEN 'Temas' THEN 2 WHEN 'Numune' THEN 3
              WHEN 'Deneme' THEN 4 WHEN 'Teklif' THEN 5 WHEN 'Pazarlık' THEN 6
              WHEN 'Sipariş' THEN 7 WHEN 'Kazanıldı' THEN 8
              WHEN 'Kaybedildi' THEN 9 ELSE 10 END
        """)
        st.dataframe(funnel,use_container_width=True,hide_index=True)

        quote_perf=query_df(db_path,"""
            SELECT q.status AS durum,COUNT(*) AS teklif_sayısı,
                   ROUND(AVG(q.margin_pct),2) AS ortalama_marj,
                   ROUND(SUM(q.profit_total_base),0) AS toplam_katkı,
                   q.base_currency AS para
            FROM quotes q
            GROUP BY q.status,q.base_currency
            ORDER BY teklif_sayısı DESC
        """)
        st.markdown("#### Teklif performansı")
        st.dataframe(quote_perf,use_container_width=True,hide_index=True)

    with customer_tab:
        customers=query_df(db_path,"""
            SELECT c.name AS müşteri,c.status AS durum,c.sector AS sektör,
                   c.owner AS sorumlu,c.annual_potential AS yıllık_potansiyel,
                   c.currency AS para,
                   COUNT(DISTINCT o.id) AS fırsat_sayısı,
                   COALESCE(SUM(CASE WHEN o.stage NOT IN ('Kaybedildi') THEN o.value ELSE 0 END),0) AS fırsat_değeri,
                   MAX(a.activity_date) AS son_aktivite
            FROM customers c
            LEFT JOIN opportunities o ON o.customer_id=c.id
            LEFT JOIN activities a ON a.customer_id=c.id
            GROUP BY c.id,c.name,c.status,c.sector,c.owner,c.annual_potential,c.currency
            ORDER BY fırsat_değeri DESC
        """)
        st.dataframe(customers,use_container_width=True,hide_index=True)

    with product_tab:
        products=query_df(db_path,"""
            SELECT o.product AS ürün,COUNT(*) AS fırsat_sayısı,
                   ROUND(SUM(o.value),0) AS toplam_fırsat,
                   ROUND(SUM(o.value*o.probability/100.0),0) AS ağırlıklı_fırsat,
                   ROUND(AVG(o.probability),1) AS ortalama_olasılık
            FROM opportunities o
            WHERE o.stage!='Kaybedildi'
            GROUP BY o.product
            ORDER BY ağırlıklı_fırsat DESC
        """)
        st.dataframe(products,use_container_width=True,hide_index=True)

        margins=query_df(db_path,"""
            SELECT product_name AS ürün,COUNT(*) AS teklif_sayısı,
                   ROUND(AVG(margin_pct),2) AS ortalama_marj,
                   ROUND(AVG(total_cost_per_kg),4) AS ortalama_maliyet,
                   ROUND(AVG(sell_price_per_kg),4) AS ortalama_satış
            FROM quotes
            GROUP BY product_name
            ORDER BY teklif_sayısı DESC
        """)
        st.markdown("#### Ürün teklif marjları")
        st.dataframe(margins,use_container_width=True,hide_index=True)

    with team_tab:
        tasks=query_df(db_path,"""
            SELECT owner AS sorumlu,
                   COUNT(*) AS toplam_görev,
                   SUM(CASE WHEN status='Tamamlandı' THEN 1 ELSE 0 END) AS tamamlanan,
                   SUM(CASE WHEN status!='Tamamlandı' AND due_date!='' AND due_date<date('now') THEN 1 ELSE 0 END) AS geciken
            FROM tasks
            GROUP BY owner
            ORDER BY geciken DESC,toplam_görev DESC
        """)
        st.dataframe(tasks,use_container_width=True,hide_index=True)

        activity=query_df(db_path,"""
            SELECT owner AS sorumlu,COUNT(*) AS aktivite_sayısı,
                   MAX(activity_date) AS son_aktivite
            FROM activities
            GROUP BY owner
            ORDER BY aktivite_sayısı DESC
        """)
        st.markdown("#### CRM aktivitesi")
        st.dataframe(activity,use_container_width=True,hide_index=True)
