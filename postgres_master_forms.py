"""Phase-one PostgreSQL master-data forms for authenticated administrators.

Forms are NOT displayed or usable unless *two separate server settings* have
been explicitly enabled. They never write SQLite, ct_staging, cash or inventory.
The operational API independently repeats the write-enabled + role guard.
No database password is logged, displayed or embedded into user input.
"""
import os

import streamlit as st

from security_admin import current_role, current_user
from scripts.postgres_operational_write import (
    create_customer,
    create_product,
    create_warehouse,
)

UI_FLAG = "AS_CONTROL_TOWER_PG_UI_WRITES_ENABLED"
ENGINE_FLAG = "AS_CONTROL_TOWER_PG_WRITES_ENABLED"

MESSAGES = {
    "duplicate_customer": "Aynı isimli müşteri zaten bulunuyor.",
    "duplicate_product": "Aynı isimli ürün zaten bulunuyor.",
    "duplicate_warehouse": "Aynı isimli depo zaten bulunuyor.",
    "invalid_customer": "Geçerli bir müşteri adı girin.",
    "invalid_product": "Geçerli bir ürün adı girin.",
    "invalid_supplier": "Geçerli bir tedarikçi adı girin.",
    "invalid_warehouse": "Depo adı, şehir veya depo tipi geçersiz.",
    "invalid_actor": "Giriş yapan kullanıcı doğrulanamadı.",
    "invalid_url": "Veritabanı bağlantısı geçersiz.",
    "schema_mismatch": "ct_app tablo yapısı beklenen şemayla uyumlu değil.",
    "disabled": "PostgreSQL kayıt işlemleri sunucuda devre dışı.",
    "forbidden": "Bu kayıt işlemi için yetkiniz bulunmuyor.",
    "failed": "Kayıt gerçekleştirilemedi. İşlem geri alındı.",
}


def postgres_master_write_enabled():
    """Two-key admin rollout. No checkbox alone can activate writes."""
    return (
        os.environ.get(UI_FLAG) == "1"
        and os.environ.get(ENGINE_FLAG) == "1"
        and os.environ.get("CT_LOCAL_POSTGRES_TEST") != "1"
    )


def _show_result(status, record_id):
    if status == "ok":
        st.success(f"PostgreSQL ct_app kaydı oluşturuldu. Kayıt no: {int(record_id)}")
    else:
        st.error(MESSAGES.get(status, "Kayıt yapılamadı; veri değiştirilmedi."))


def render_postgres_master_forms(url):
    """Renders admin forms only when explicitly enabled on the server."""
    st.markdown("#### 🔒 PostgreSQL Kayıt Yönetimi")
    role = current_role()
    user = current_user() or {}
    if role != "ADMIN" or not user.get("username"):
        st.error("PostgreSQL kayıt yönetimi yalnızca giriş yapmış ADMIN içindir.")
        return
    if not postgres_master_write_enabled():
        st.info(
            "PostgreSQL müşteri, ürün ve depo kayıt formları hazırlandı, "
            "ancak güvenlik gereği kapalı. Sunucu ayarlarında iki ayrı "
            "onaylı etkinleştirme yapılmadan veri kaydedilemez."
        )
        return
    if not url:
        st.error("DATABASE_URL sunucu ayarı bulunamadı.")
        return

    st.warning(
        "Bu bölüm seçilirse kayıtlar kalıcı PostgreSQL ct_app veritabanına yazılır. "
        "Mevcut SQLite ekranlarına otomatik aktarılmaz. "
        "Finans ve stok hareketi oluşturma burada kapalıdır."
    )
    actor = str(user["username"])

    with st.expander("👥 Yeni PostgreSQL müşterisi"):
        with st.form("ct_pg_customer_create_form"):
            name = st.text_input("Müşteri / firma unvanı", key="ct_pg_customer_name")
            country = st.text_input(
                "Ülke", value="Türkiye", key="ct_pg_customer_country"
            )
            sector = st.text_input("Sektör", key="ct_pg_customer_sector")
            confirmed = st.checkbox(
                "Bu müşteri kaydının kalıcı ct_app veritabanına "
                "yazılmasını onaylıyorum.",
                key="ct_pg_customer_confirm",
            )
            submitted = st.form_submit_button("PostgreSQL müşterisi oluştur")
        if submitted:
            if not confirmed:
                st.warning("Kalıcı kayıt için onay kutusunu işaretleyin.")
            else:
                status, ident = create_customer(
                    url, role, name, country=country, sector=sector, actor=actor,
                )
                _show_result(status, ident)

    with st.expander("🧪 Yeni PostgreSQL ürün kataloğu kaydı"):
        with st.form("ct_pg_product_create_form"):
            product_name = st.text_input("Ürün adı", key="ct_pg_product_name")
            supplier = st.text_input("Üretici / tedarikçi", key="ct_pg_supplier")
            category = st.text_input("Kategori", key="ct_pg_product_category")
            confirmed = st.checkbox(
                "Bu ürünün kalıcı ct_app kataloğuna yazılmasını onaylıyorum.",
                key="ct_pg_product_confirm",
            )
            submitted = st.form_submit_button("PostgreSQL ürünü oluştur")
        if submitted:
            if not confirmed:
                st.warning("Kalıcı kayıt için onay kutusunu işaretleyin.")
            else:
                status, ident = create_product(
                    url, role, product_name, supplier, category=category, actor=actor,
                )
                _show_result(status, ident)

    with st.expander("🏬 Yeni PostgreSQL deposu"):
        with st.form("ct_pg_warehouse_create_form"):
            warehouse = st.text_input("Depo adı", key="ct_pg_warehouse_name")
            city = st.text_input("Şehir", key="ct_pg_warehouse_city")
            warehouse_type = st.selectbox(
                "Depo tipi", ["Normal Depo", "Antrepo", "Soğuk Depo"],
                key="ct_pg_warehouse_type",
            )
            confirmed = st.checkbox(
                "Bu deponun kalıcı ct_app veritabanına yazılmasını onaylıyorum.",
                key="ct_pg_warehouse_confirm",
            )
            submitted = st.form_submit_button("PostgreSQL deposu oluştur")
        if submitted:
            if not confirmed:
                st.warning("Kalıcı kayıt için onay kutusunu işaretleyin.")
            else:
                status, ident = create_warehouse(
                    url, role, warehouse, city=city,
                    warehouse_type=warehouse_type, actor=actor,
                )
                _show_result(status, ident)
