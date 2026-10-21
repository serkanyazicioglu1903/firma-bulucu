"""Real-input, no-save quote estimator for logged-in AS Control Tower staff.

This screen never reads or writes a company database. It never uses demo
records or infers FX. A company selection is a quotation label ONLY, not
authorization to view another company's data. Results are session-only.
"""
import csv
from datetime import datetime, timezone
from decimal import Decimal
from io import StringIO

import streamlit as st

from scripts.group_company_catalog import COMPANY_LABELS
from scripts.real_quote_estimator import QuoteInputError, calculate_real_quote
from scripts.purchase_draft_preview import PurchaseDraftError, purchase_draft_csv
from security_admin import current_role, current_user


_ALLOWED = frozenset({"ADMIN", "SALES", "PURCHASING", "FINANCE"})
_CURRENCIES = ("EUR", "USD", "GBP", "TRY")
_FIELD_KEYS = (
    "ct_rq_customer", "ct_rq_product", "ct_rq_qty", "ct_rq_qty_unit", "ct_rq_buy",
    "ct_rq_sell", "ct_rq_buy_fx", "ct_rq_sell_fx",
    "ct_rq_freight", "ct_rq_customs", "ct_rq_other",
    "ct_rq_handling", "ct_rq_rate", "ct_rq_pre_pct",
    "ct_rq_pre_days", "ct_rq_balance_days", "ct_rq_stock_days",
    "ct_rq_customer_days", "ct_rq_commission", "ct_rq_margin",
    "ct_rq_fx_basis",
    "ct_rq_buy_ccy", "ct_rq_sell_ccy", "ct_rq_base_ccy",
)
_RESULT_KEY = "ct_real_quote_result"
_OWNER_KEY = "ct_real_quote_session_owner"
_PO_CSV_KEY = "ct_purchase_draft_csv"
_PO_FIELD_KEYS = (
    "ct_po_supplier", "ct_po_product", "ct_po_warehouse", "ct_po_reference",
)


def _reset_quote():
    """Company change discards prior company input and calculated results."""
    for key in (*_FIELD_KEYS, *_PO_FIELD_KEYS, _RESULT_KEY, _PO_CSV_KEY):
        st.session_state.pop(key, None)


def _reset_result():
    """Changing currency invalidates quotes AND previous FX manual inputs."""
    for key in (_RESULT_KEY, _PO_CSV_KEY, *_PO_FIELD_KEYS, "ct_rq_buy_fx", "ct_rq_sell_fx"):
        st.session_state.pop(key, None)


def _reset_quantity_unit():
    """Never silently reinterpret an existing kg amount as metric tons."""
    st.session_state.pop("ct_rq_qty", None)
    st.session_state.pop(_RESULT_KEY, None)
    st.session_state.pop(_PO_CSV_KEY, None)
    for key in _PO_FIELD_KEYS:
        st.session_state.pop(key, None)


def _bound_session():
    """Prevent one signed-in staff session inheriting the previous user's quote.

    This is a UI memory hygiene boundary only, never tenant authentication.
    """
    user = current_user() or {}
    username = user.get("username") if isinstance(user, dict) else None
    session_id = st.session_state.get("ct_session_id")
    if not isinstance(username, str) or not username or not session_id:
        _reset_quote()
        return False
    marker = (username, session_id)
    if st.session_state.get(_OWNER_KEY) != marker:
        _reset_quote()
        st.session_state.pop("ct_rq_company", None)
        st.session_state[_OWNER_KEY] = marker
    return True


def _fmt(value, places=4):
    return f"{value:,.{places}f}"


def quote_summary_csv(result):
    """Return export of numeric estimates only; no customer or free-text values.

    Spreadsheet formula injection is impossible: all keys are fixed labels,
    values are server-calculated Decimals and predefined currency/company codes.
    """
    if not isinstance(result, dict) or not result:
        raise ValueError("missing_result")
    output = StringIO()
    writer = csv.writer(output)
    writer.writerow(("Kalem", "Tutar", "Para birimi"))
    writer.writerow(("Miktar (kg)", str(result["quantity_kg"]), "kg"))
    writer.writerow(("Miktar (ton)", str(result["quantity_kg"] / Decimal(1000)), "ton"))
    money = result["base_currency"]
    for label, key in (
        ("Mal bedeli", "goods_base"),
        ("Lojistik gümrük depo", "logistics_base"),
        ("İthal maliyet toplam", "landed_total_base"),
        ("Finansman toplam", "finance_total_base"),
        ("Gerçek toplam maliyet", "total_cost_base"),
        ("Toplam satış (KDV hariç)", "gross_sales_base"),
        ("Gerçek maliyet kg", "cost_per_kg_base"),
        ("Toplam net katkı", "profit_base"),
        ("Net katkı kg", "profit_per_kg_base"),
        ("Net marj yüzde", "margin_pct"),
    ):
        amount = result[key]
        writer.writerow((label, "" if amount is None else str(amount), "%" if "yüzde" in label else money))
    writer.writerow((
        "Başabaş satış fiyatı / kg", str(result["break_even_sell_price"]),
        result["sell_currency"],
    ))
    writer.writerow((
        "Hedef marj satış fiyatı / kg", str(result["required_sell_price"]),
        result["sell_currency"],
    ))
    writer.writerow(("Şirket etiketi", result["company_code"], ""))
    writer.writerow(("Beyan", "Manuel giriş, ön hesap; veritabanına kaydedilmedi", ""))
    return output.getvalue().encode("utf-8-sig")


def _quantity_to_kg(value, unit):
    """Convert an entered kg/ton quantity; prices remain per kilogram."""
    if unit not in ("kg", "ton"):
        raise QuoteInputError("quantity_required")
    try:
        amount = Decimal(str(value))
    except (ValueError, ArithmeticError, TypeError):
        raise QuoteInputError("quantity_required") from None
    quantity = amount * (Decimal(1000) if unit == "ton" else Decimal(1))
    if not quantity.is_finite() or quantity <= 0 or quantity > Decimal("1000000000"):
        raise QuoteInputError("quantity_required")
    return quantity


def render_real_quote_workspace():
    """Manual quote workflow, independent of demo customer/product masters."""
    if current_role() not in _ALLOWED:
        st.warning("Teklif hesaplama erişimi bu rol için açık değil.")
        return
    if not _bound_session():
        st.error("Teklif ön hesabı için doğrulanmış oturum gerekli; yeniden giriş yap.")
        return

    st.subheader("🧮 Gerçek Teklif ve Kârlılık — Kaydetmeden Hesapla")
    st.caption(
        "Tüm tutarları sen giriyorsun: örnek/demo veri, otomatik kur, "
        "müşteri veya ürün veritabanı yüklenmez. Sonuçlar yalnızca bu "
        "oturumda görünür; Supabase'e veya eski SQLite'a kaydedilmez."
    )
    st.warning(
        "Şirket seçimi hesap çıktısı içindir, şirket erişim yetkisi değildir. "
        "Gümrük, KDV, navlun, kur ve ödeme şartlarını güncel evrakla doğrula. "
        "KDV hesapta yer almaz; gümrük ve diğer vergileri toplam tutar olarak gir."
    )

    c, p, s, base = st.columns(4)
    company_code = c.selectbox(
        "Teklifi veren şirket etiketi",
        tuple(COMPANY_LABELS),
        format_func=lambda code: COMPANY_LABELS[code],
        key="ct_rq_company",
        on_change=_reset_quote,
    )
    buy_currency = p.selectbox(
        "Alış para birimi", _CURRENCIES,
        key="ct_rq_buy_ccy", on_change=_reset_result,
    )
    sell_currency = s.selectbox(
        "Satış para birimi", _CURRENCIES,
        key="ct_rq_sell_ccy", on_change=_reset_result,
    )
    base_currency = base.selectbox(
        "Hesap para birimi", _CURRENCIES,
        key="ct_rq_base_ccy", on_change=_reset_result,
    )

    quantity_unit = st.selectbox(
        "Miktar birimi", ("kg", "ton"), key="ct_rq_qty_unit",
        on_change=_reset_quantity_unit,
    )
    st.caption("Alış ve satış fiyatları daima kg başınadır; 1 ton = 1.000 kg.")

    with st.form("ct_real_quote_form"):
        x1, x2 = st.columns(2)
        x1.text_input("Müşteri / fırsat (isteğe bağlı)", key="ct_rq_customer")
        x2.text_input("Ürün / hammadde (isteğe bağlı)", key="ct_rq_product")

        st.markdown("#### 1. Miktar, fiyat ve manuel kur")
        a, b1, d = st.columns(3)
        quantity = a.number_input(
            f"Miktar ({quantity_unit})", min_value=0.0,
            max_value=1000000000.0, value=0.0,
            step=1.0 if quantity_unit == "ton" else 1000.0,
            key="ct_rq_qty",
        )
        purchase = b1.number_input(
            f"Alış fiyatı ({buy_currency}/kg)", min_value=0.0,
            value=0.0, step=0.01, format="%.4f", key="ct_rq_buy",
        )
        offered = d.number_input(
            f"Satış fiyatı ({sell_currency}/kg) — boşsa 0",
            min_value=0.0, value=0.0, step=0.01,
            format="%.4f", key="ct_rq_sell",
        )
        x, y = st.columns(2)
        if buy_currency == base_currency:
            x.caption(f"Alış kuru: 1 {buy_currency} = 1 {base_currency}")
            purchase_fx = 1.0
        else:
            purchase_fx = x.number_input(
                f"1 {buy_currency} = kaç {base_currency}?",
                min_value=0.0, value=0.0, step=0.01,
                format="%.6f", key="ct_rq_buy_fx",
            )
        if sell_currency == base_currency:
            y.caption(f"Satış kuru: 1 {sell_currency} = 1 {base_currency}")
            offered_fx = 1.0
        else:
            offered_fx = y.number_input(
                f"1 {sell_currency} = kaç {base_currency}?",
                min_value=0.0, value=0.0, step=0.01,
                format="%.6f", key="ct_rq_sell_fx",
            )
        st.text_input(
            "Kurun kaynağı / tarihi (manuel not)",
            key="ct_rq_fx_basis",
            placeholder="Örn. banka teyidi ve teklif tarihi",
        )

        st.markdown("#### 2. İthalat ve lojistik toplamları")
        l1, l2, l3, l4 = st.columns(4)
        freight = l1.number_input(
            f"Navlun ({base_currency})", min_value=0.0,
            value=0.0, step=100.0, key="ct_rq_freight",
        )
        duties = l2.number_input(
            f"Gümrük / harç toplamı ({base_currency})", min_value=0.0,
            value=0.0, step=100.0, key="ct_rq_customs",
        )
        other = l3.number_input(
            f"Diğer ithalat gideri ({base_currency})", min_value=0.0,
            value=0.0, step=100.0, key="ct_rq_other",
        )
        handling = l4.number_input(
            f"Depo / iç nakliye ({base_currency})", min_value=0.0,
            value=0.0, step=100.0, key="ct_rq_handling",
        )

        st.markdown("#### 3. Ödeme takvimi ve finansman")
        st.caption(
            "Ön ödeme varıştan önce, kalan tedarikçi ödemesi varıştan sonra, "
            "müşteri tahsilatı ise stok ve satış vadesinin sonunda varsayılır."
        )
        t1, t2, t3 = st.columns(3)
        prepct = t1.number_input(
            "Tedarikçi ön ödeme %", min_value=0.0, max_value=100.0,
            value=0.0, step=5.0, key="ct_rq_pre_pct",
        )
        pre_days = t2.number_input(
            "Ön ödeme → varış (gün)", min_value=0,
            value=0, max_value=3650, key="ct_rq_pre_days",
        )
        balance_days = t3.number_input(
            "Kalan ödeme varıştan sonra (gün)", min_value=0,
            value=0, max_value=3650, key="ct_rq_balance_days",
        )
        t4, t5, t6 = st.columns(3)
        stock_days = t4.number_input(
            "Stokta bekleme (gün)", min_value=0,
            value=0, max_value=3650, key="ct_rq_stock_days",
        )
        customer_days = t5.number_input(
            "Müşteri tahsilat vadesi (gün)", min_value=0,
            value=0, max_value=3650, key="ct_rq_customer_days",
        )
        annual_rate = t6.number_input(
            "Yıllık finansman maliyeti %", min_value=0.0,
            max_value=100.0, value=0.0, step=1.0, key="ct_rq_rate",
        )
        t7, t8 = st.columns(2)
        commission = t7.number_input(
            "Satış komisyonu / iskonto %", min_value=0.0,
            max_value=99.0, value=0.0, step=0.5, key="ct_rq_commission",
        )
        target = t8.number_input(
            "Hedef net katkı marjı %", min_value=0.0,
            max_value=99.0, value=0.0, step=0.5, key="ct_rq_margin",
        )
        submit = st.form_submit_button(
            "🧮 Gerçek maliyet ve teklif fiyatını hesapla",
            type="primary", width="stretch",
        )

    if submit:
        # An older exported purchase request must never survive a new quote.
        for key in (*_PO_FIELD_KEYS, _PO_CSV_KEY, _RESULT_KEY):
            st.session_state.pop(key, None)
        try:
            result = calculate_real_quote(
                company_code=company_code,
                quantity_kg=_quantity_to_kg(quantity, quantity_unit),
                buy_price_per_kg=purchase, buy_currency=buy_currency,
                buy_fx_to_base=purchase_fx, base_currency=base_currency,
                sell_price_per_kg=offered, sell_currency=sell_currency,
                sell_fx_to_base=offered_fx, freight_total_base=freight,
                customs_total_base=duties, import_other_total_base=other,
                handling_total_base=handling,
                annual_finance_rate_pct=annual_rate, prepayment_pct=prepct,
                prepayment_lead_days=pre_days,
                supplier_balance_due_days=balance_days,
                stock_days=stock_days, customer_credit_days=customer_days,
                sales_commission_pct=commission, target_margin_pct=target,
            )
        except QuoteInputError as error:
            messages = {
                "company_required": "Geçerli şirket etiketi seç.",
                "quantity_required": "Miktar sıfırdan büyük olmalı.",
                "buy_price_required": "Alış fiyatı sıfırdan büyük olmalı.",
                "fx_required": "Farklı para biriminde gerçek manuel kur girilmelidir.",
            }
            st.error(messages.get(error.code, "Geçersiz tutar, tarih veya oran; kontrol et."))
        else:
            st.session_state[_RESULT_KEY] = result
    result = st.session_state.get(_RESULT_KEY)
    if result is None:
        st.info("Hesaplamak için miktar, alış fiyatı ve gerekiyorsa manuel kur gir.")
        return

    st.markdown("#### Sonuç — Ön Ticari Hesap")
    st.caption(
        f"Hesaplanan miktar: {_fmt(result['quantity_kg'], 0)} kg "
        f"({_fmt(result['quantity_kg'] / Decimal(1000), 3)} ton). "
        "Bütün birim fiyatlar kg başınadır."
    )
    columns = st.columns(4)
    columns[0].metric(
        "İthal maliyet / kg", _fmt(result["landed_per_kg_base"])
        + " " + base_currency,
    )
    columns[1].metric(
        "Finansman / kg", _fmt(result["finance_per_kg_base"])
        + " " + base_currency,
    )
    columns[2].metric(
        "Gerçek maliyet / kg", _fmt(result["cost_per_kg_base"])
        + " " + base_currency,
    )
    columns[3].metric(
        "Hedef fiyat / kg", _fmt(result["required_sell_price"])
        + " " + sell_currency,
    )
    st.caption(
        "Başabaş: " + _fmt(result["break_even_sell_price"]) + " "
        + sell_currency + "/kg · Malların ağırlıklı finansman süresi: "
        + _fmt(result["weighted_goods_finance_days"], 1) + " gün"
    )
    if result["profit_base"] is None:
        st.info("Satış fiyatı girilmedi. Hedef fiyat hesaplandı; kâr henüz hesaplanmadı.")
    else:
        st.metric(
            "Toplam satış tutarı (KDV hariç)",
            _fmt(result["gross_sales_base"], 2) + " " + base_currency,
        )
        result_cols = st.columns(3)
        result_cols[0].metric(
            "Toplam net katkı",
            _fmt(result["profit_base"], 2) + " " + base_currency,
        )
        result_cols[1].metric(
            "Net katkı / kg",
            _fmt(result["profit_per_kg_base"]) + " " + base_currency,
        )
        result_cols[2].metric(
            "Net katkı marjı", "%" + _fmt(result["margin_pct"], 2),
        )
        if result["profit_base"] < 0:
            st.error("Hesaplanan teklif zarar gösteriyor; fiyat veya maliyetleri incele.")
        elif not result["meets_target"]:
            st.warning("Teklif kârlı ancak hedef net katkı marjının altında.")
        else:
            st.success("Teklif, belirtilen hedef net katkı marjını karşılıyor.")

    st.download_button(
        "Hesap özetini CSV indir — kaydetmez",
        data=quote_summary_csv(result),
        file_name="AS_Control_Tower_Teklif_On_Hesap.csv",
        mime="text/csv",
        key="ct_rq_download", width="stretch",
    )
    st.caption(
        "Tahmin; doğrulanmış ithalat vergisi, sözleşme, nakit akışı ve "
        "muhasebe mutabakatının yerine geçmez. Mevcut sistemde sipariş "
        "veya teklif kaydı oluşturulmadı."
    )

    # PO is a human-review CSV only. Creating a purchase order in PostgreSQL
    # would require verified legal IDs, per-company server grants and a
    # separately approved atomic transaction that does not exist in production.
    with st.expander("📋 Tekliften satın alma talep taslağı — kaydetmeden"):
        st.warning(
            "Bu dosya sadece ONAYSIZ satın alma taslağıdır. "
            "Şirket seçimi yasal yetki veya gerçek şirket ayrımı değildir. "
            "Sipariş, depo girişi, borç veya Supabase kaydı oluşturmaz."
        )
        with st.form("ct_po_draft_form"):
            supplier = st.text_input("Tedarikçi adı (manuel)", key="ct_po_supplier")
            product = st.text_input(
                "Satın alınacak ürün adı",
                value=str(st.session_state.get("ct_rq_product") or "").strip(),
                key="ct_po_product",
            )
            warehouse = st.text_input(
                "Teslim deposu / yeri (manuel)", key="ct_po_warehouse"
            )
            reference = st.text_input(
                "İç takip referansı (isteğe bağlı)", key="ct_po_reference"
            )
            prepare = st.form_submit_button(
                "📋 Onaysız satın alma taslağı hazırla", width="stretch"
            )
        if prepare:
            st.session_state.pop(_PO_CSV_KEY, None)
            try:
                data = purchase_draft_csv(
                    result,
                    company_code=company_code,
                    supplier=supplier,
                    product_name=product,
                    warehouse_name=warehouse,
                    internal_reference=reference,
                )
            except PurchaseDraftError:
                st.error(
                    "Taslak hazırlanamadı. Tedarikçi, ürün ve teslim deposu "
                    "gerekli; formül işaretleri veya geçersiz tutar kullanılmaz."
                )
            else:
                st.session_state[_PO_CSV_KEY] = data
        if _PO_CSV_KEY in st.session_state:
            st.success("Onaysız satın alma taslağı hazır. Gerçek sipariş kaydedilmedi.")
            st.download_button(
                "⬇️ Satın alma taslağını CSV indir",
                data=st.session_state[_PO_CSV_KEY],
                file_name="AS_Control_Tower_Onaysiz_Satin_Alma_Taslagi.csv",
                mime="text/csv",
                key="ct_po_draft_download",
                width="stretch",
            )
