"""Lightweight authenticated Streamlit route for a no-save quote preview.

Deliberately avoids loading the large legacy Control Tower interface,
customer/product masters, or any PostgreSQL/SQLite business records.
"""
import streamlit as st

from real_quote_workspace import render_real_quote_workspace
from scoped_company_workspace_ui import company_review_mode_state
from security_admin import login_gate, logout_button


st.set_page_config(
    page_title="AS Control Tower | Gerçek Teklif",
    page_icon="🧮",
    layout="wide",
    initial_sidebar_state="collapsed",
)

# Exactly the same application-wide login requirement as app.py.
if not login_gate():
    st.stop()

# The exclusive company-review mode suppresses all unscoped legacy and
# quote screens, including directly addressed Streamlit multipage routes.
# Do not infer permission from the quote's display-only company selector.
if company_review_mode_state() != "disabled":
    st.error(
        "Dört şirket inceleme modu etkin veya geçersiz. Şirket yetkisi "
        "doğrulanmayan teklif ekranı güvenlik nedeniyle kapalı."
    )
    st.stop()

logout_button()
st.title("🧮 AS Control Tower — Gerçek Teklif / Kârlılık")
st.caption("Bağımsız, kayıtsız hesaplama: müşteri/ürün kaydı ve demo veri gerekmez.")
st.page_link("app.py", label="← Ana uygulamaya dön")
render_real_quote_workspace()
