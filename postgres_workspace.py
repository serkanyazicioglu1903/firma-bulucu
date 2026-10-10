"""Read-only, ADMIN-only PostgreSQL operational workspace in Control Tower.

Deliberately separate from the existing SQLite screens. No automatic reads,
dual-writes, secrets display, schema changes, or demo inserts.
"""
import pandas as pd
import streamlit as st

from security_admin import current_role
from scripts.postgres_operational_read import (
    WORKSPACE_QUERIES,
    read_operational_counts,
    read_operational_workspace,
)


def render_postgres_workspace():
    st.markdown("### 🗄️ PostgreSQL Operasyon 360")
    st.caption(
        "Supabase ct_app üzerinde doğrudan kayıt görüntüleme. "
        "CRM, satın alma, stok, kalite ve finans verileri yalnızca okunur."
    )
    if current_role() != "ADMIN":
        st.error("Bu bölüm yalnızca ADMIN rolüne açıktır.")
        return

    try:
        url = st.secrets.get("DATABASE_URL", "")
    except Exception:
        url = ""
    if not url:
        st.warning("Supabase bağlantısı yapılandırılmamış.")
        return

    st.info(
        "Bu panel PostgreSQL ct_app kullanır; diğer Control Tower ekranları "
        "henüz SQLite üzerindedir. Veri girişi, ödeme ve otomatik geçiş kapalıdır."
    )
    if st.button("PostgreSQL genel durumu yenile", key="ct_pg_360_refresh"):
        status, counts = read_operational_counts(url)
        if status != "ok":
            st.error("PostgreSQL genel durumu okunamadı.")
        else:
            customer_count = counts.get("customers", 0)
            order_count = counts.get("purchase_orders", 0)
            stock_count = counts.get("inventory_lots", 0)
            quality_count = counts.get("quality_cases", 0)
            a, b, c, d = st.columns(4)
            a.metric("Müşteriler", customer_count)
            b.metric("Satın alma", order_count)
            c.metric("Stok lotları", stock_count)
            d.metric("Kalite dosyaları", quality_count)
            st.caption(
                "Yalnızca ct_app kayıt sayıları; mevcut SQLite kayıtlarını kapsamaz."
            )

    workspace = st.selectbox(
        "PostgreSQL bölümü",
        list(WORKSPACE_QUERIES),
        key="ct_pg_360_workspace",
    )
    if st.button("Seçilen PostgreSQL kayıtlarını getir", key="ct_pg_360_load"):
        status, records = read_operational_workspace(url, workspace)
        if status != "ok":
            st.error(
                "ct_app kayıtları güvenli şekilde okunamadı. "
                "Şemayı ve Supabase bağlantısını kontrol edin."
            )
            return
        st.caption(
            f"{workspace}: en fazla 100 son kayıt gösteriliyor; "
            "hiçbir kayıt eklenmedi veya değiştirilmedi."
        )
        if not records:
            st.info("Bu PostgreSQL bölümünde henüz kayıt yok.")
        else:
            st.dataframe(
                pd.DataFrame.from_records(records),
                width="stretch", hide_index=True,
            )
