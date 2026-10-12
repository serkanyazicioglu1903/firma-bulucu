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

from scripts.company_runtime import runtime_mode
from company_runtime_ui import render_company_runtime

# Exactly the same application-wide login requirement as app.py.
if not login_gate():
    st.stop()

if runtime_mode() != "disabled":
    if runtime_mode() == "invalid" or company_review_mode_state() != "disabled":
        st.error("Şirket çalışma modu geçersiz veya çelişkili; eski ekranlar kapalı.")
    else:
        logout_button()
        render_company_runtime()
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
# Standalone page: use Streamlit’s native multipage navigation for return.
render_real_quote_workspace()
