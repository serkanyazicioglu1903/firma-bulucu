import sqlite3
from datetime import date
from pathlib import Path

import pandas as pd
import streamlit as st

from ai_manager import render_ai_manager
from management_reports import render_management_reports
from security_admin import audit_sql_write, authorize_write, current_user


def connect(db_path):
    conn=sqlite3.connect(Path(db_path),check_same_thread=False)
    conn.row_factory=sqlite3.Row
    return conn


def query_df(db_path,sql,params=()):
    with connect(db_path) as conn:
        return pd.read_sql_query(sql,conn,params=params)


def execute(db_path,sql,params=()):
    if not authorize_write(sql):
        raise PermissionError("Bu işlem mevcut kullanıcı rolü için yetkili değil.")
    with connect(db_path) as conn:
        conn.execute(sql,params)
        conn.commit()
    audit_sql_write(db_path,sql)


def user_header(role):
    user=current_user() or {}
    st.markdown("### 👤 " + str(user.get("display_name") or user.get("username") or "Kullanıcı"))
    st.caption("Rol: " + role)


def render_sales(db_path):
    user_header("SALES")
    dash,crm,pipeline,tasks=st.tabs(["📊 Özet","👥 CRM","💰 Pipeline","✅ Görevler"])
    owner=str((current_user() or {}).get("display_name") or "")

    with dash:
        opp=query_df(db_path,"""
            SELECT COUNT(*) AS fırsat,
                   COALESCE(SUM(value*probability/100.0),0) AS ağırlıklı
            FROM opportunities
            WHERE stage NOT IN ('Kazanıldı','Kaybedildi')
              AND (?='' OR owner=?)
        """,(owner,owner))
        c1,c2=st.columns(2)
        c1.metric("Aktif fırsat",int(opp.iloc[0]["fırsat"] or 0))
        c2.metric("Ağırlıklı pipeline",f"{float(opp.iloc[0]['ağırlıklı'] or 0):,.0f} EUR")

    with crm:
        df=query_df(db_path,"""
            SELECT name AS müşteri,country AS ülke,sector AS sektör,status AS durum,
                   owner AS sorumlu,contact_name AS kontak,contact_email AS email,phone
            FROM customers
            ORDER BY name
        """)
        st.dataframe(df,width="stretch",hide_index=True)

        customers=query_df(db_path,"SELECT id,name FROM customers ORDER BY name")
        if not customers.empty:
            with st.form("sales_quick_activity",clear_on_submit=True):
                cname=st.selectbox("Müşteri",customers["name"].tolist())
                summary=st.text_area("Görüşme notu *")
                next_action=st.text_input("Sonraki aksiyon")
                due=st.date_input("Takip tarihi",value=date.today())
                if st.form_submit_button("Görüşmeyi kaydet",type="primary") and summary.strip():
                    cid=int(customers.loc[customers["name"]==cname,"id"].iloc[0])
                    execute(db_path,"""INSERT INTO activities
                        (customer_id,activity_type,activity_date,summary,next_action,next_action_date,owner)
                        VALUES (?,'Not',?,?,?,?,?)""",
                        (cid,str(date.today()),summary,next_action,str(due),owner))
                    if next_action.strip():
                        execute(db_path,"""INSERT INTO tasks
                            (title,related_to,owner,priority,due_date,status,notes)
                            VALUES (?,?,?,'Orta',?,'Açık','Satış portalından')""",
                            (next_action,cname,owner,str(due)))
                    st.success("Kaydedildi.")
                    st.rerun()

    with pipeline:
        df=query_df(db_path,"""
            SELECT o.id,c.name AS müşteri,o.product AS ürün,o.stage AS aşama,
                   o.value AS değer,o.currency AS para,o.probability AS olasılık,
                   o.next_action AS sonraki_aksiyon,o.due_date AS tarih,o.owner AS sorumlu
            FROM opportunities o
            LEFT JOIN customers c ON c.id=o.customer_id
            WHERE (?='' OR o.owner=?)
            ORDER BY o.value DESC
        """,(owner,owner))
        st.dataframe(df,width="stretch",hide_index=True)

    with tasks:
        df=query_df(db_path,"""
            SELECT id,title AS görev,related_to AS ilgili,priority AS öncelik,
                   due_date AS tarih,status AS durum
            FROM tasks
            WHERE (?='' OR owner=?)
            ORDER BY due_date
        """,(owner,owner))
        st.dataframe(df,width="stretch",hide_index=True)


def render_purchasing(db_path):
    user_header("PURCHASING")
    po,ship,stock,tasks=st.tabs(["📄 PO","🚛 Sevkiyat","🏬 Stok","✅ Görevler"])
    with po:
        st.dataframe(query_df(db_path,"""
            SELECT po_number AS PO,supplier AS tedarikçi,product_name AS ürün,
                   quantity_kg/1000.0 AS ton,unit_price AS fiyat,currency AS para,
                   incoterm,confirmed_load_date AS yükleme,status AS durum
            FROM purchase_orders ORDER BY id DESC
        """),width="stretch",hide_index=True)
    with ship:
        st.dataframe(query_df(db_path,"""
            SELECT po.po_number AS PO,po.product_name AS ürün,s.quantity_kg/1000.0 AS ton,
                   s.etd,s.eta,s.status AS durum,s.lot_number AS lot
            FROM shipments s JOIN purchase_orders po ON po.id=s.purchase_order_id
            ORDER BY s.id DESC
        """),width="stretch",hide_index=True)
    with stock:
        st.dataframe(query_df(db_path,"""
            SELECT il.product_name AS ürün,w.name AS depo,il.lot_number AS lot,
                   il.expiry_date AS SKT,il.quantity_available_kg/1000.0 AS ton,
                   il.quantity_reserved_kg/1000.0 AS rezerve_ton,
                   il.quality_status AS kalite
            FROM inventory_lots il JOIN warehouses w ON w.id=il.warehouse_id
            ORDER BY il.id DESC
        """),width="stretch",hide_index=True)
    with tasks:
        st.dataframe(query_df(db_path,"""
            SELECT id,title AS görev,related_to AS ilgili,owner AS sorumlu,
                   priority AS öncelik,due_date AS tarih,status AS durum
            FROM tasks WHERE status!='Tamamlandı' ORDER BY due_date
        """),width="stretch",hide_index=True)


def render_finance(db_path):
    user_header("FINANCE")
    ar,ap,cash,quotes,reports=st.tabs(["💰 Alacak","💸 Borç","🏦 Nakit","🧮 Teklif","📈 Rapor"])
    with ar:
        st.dataframe(query_df(db_path,"""
            SELECT c.name AS müşteri,r.invoice_no AS fatura,r.due_date AS vade,
                   r.amount-r.paid_amount AS kalan,r.currency AS para,r.status AS durum
            FROM receivables r JOIN customers c ON c.id=r.customer_id
            WHERE r.status!='İptal' ORDER BY r.due_date
        """),width="stretch",hide_index=True)
    with ap:
        st.dataframe(query_df(db_path,"""
            SELECT supplier AS tedarikçi,invoice_no AS fatura,due_date AS vade,
                   amount-paid_amount AS kalan,currency AS para,status AS durum
            FROM payables WHERE status!='İptal' ORDER BY due_date
        """),width="stretch",hide_index=True)
    with cash:
        st.dataframe(query_df(db_path,"""
            SELECT name AS hesap,currency AS para,balance AS bakiye,
                   fx_to_base AS yönetim_kuru,base_currency AS yönetim_para
            FROM cash_accounts WHERE active=1 ORDER BY name
        """),width="stretch",hide_index=True)
    with quotes:
        st.dataframe(query_df(db_path,"""
            SELECT q.id,c.name AS müşteri,q.product_name AS ürün,
                   q.sell_price_per_kg AS satış,q.total_cost_per_kg AS maliyet,
                   q.margin_pct AS marj,q.profit_total_base AS katkı,
                   q.base_currency AS para,q.status AS durum
            FROM quotes q LEFT JOIN customers c ON c.id=q.customer_id
            ORDER BY q.id DESC LIMIT 100
        """),width="stretch",hide_index=True)
    with reports:
        render_management_reports(db_path)


def render_quality(db_path):
    user_header("QUALITY")
    cases,docs,regs,tasks=st.tabs(["🚨 Kalite/Claim","📜 Belgeler","🌍 Regülasyon","✅ Görevler"])
    with cases:
        st.dataframe(query_df(db_path,"""
            SELECT case_no AS dosya,product_name AS ürün,severity AS önem,status AS durum,
                   affected_quantity_kg AS etkilenen_kg,estimated_loss AS zarar,
                   currency AS para,owner AS sorumlu,target_close_date AS hedef
            FROM quality_cases
            WHERE status NOT IN ('Kapandı','İptal')
            ORDER BY id DESC
        """),width="stretch",hide_index=True)
    with docs:
        st.dataframe(query_df(db_path,"""
            SELECT owner_name AS sahip,document_type AS belge,market_country AS pazar,
                   expiry_date AS bitiş,responsible AS sorumlu,status AS durum
            FROM compliance_documents ORDER BY expiry_date
        """),width="stretch",hide_index=True)
    with regs:
        st.dataframe(query_df(db_path,"""
            SELECT product_name AS ürün,market_country AS ülke,requirement_type AS tip,
                   status AS durum,next_action AS aksiyon,due_date AS tarih,
                   responsible AS sorumlu
            FROM regulatory_items ORDER BY due_date
        """),width="stretch",hide_index=True)
    with tasks:
        st.dataframe(query_df(db_path,"""
            SELECT id,title AS görev,related_to AS ilgili,owner AS sorumlu,
                   priority AS öncelik,due_date AS tarih,status AS durum
            FROM tasks WHERE status!='Tamamlandı' ORDER BY due_date
        """),width="stretch",hide_index=True)


def render_viewer(db_path):
    user_header("VIEWER")
    reports,ai=st.tabs(["📈 Yönetim Raporları","🤖 AI Yönetici"])
    with reports:
        render_management_reports(db_path)
    with ai:
        render_ai_manager(db_path)


def render_role_portal(db_path,role):
    role=str(role or "").upper()
    if role=="SALES":
        render_sales(db_path)
    elif role=="PURCHASING":
        render_purchasing(db_path)
    elif role=="FINANCE":
        render_finance(db_path)
    elif role=="QUALITY":
        render_quality(db_path)
    elif role=="VIEWER":
        render_viewer(db_path)
    else:
        st.error("Bu rol için portal tanımlı değil: " + role)
