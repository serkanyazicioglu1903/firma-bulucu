"""Persistent four-company DEMO workspace. NOT a production authorization layer.

Uses only ct_demo schema. Every business query is scoped by a fixed company
code selected after the existing app login. No ct_app records are modified.
"""
from decimal import Decimal, InvalidOperation
import streamlit as st

from scripts.group_company_catalog import COMPANY_LABELS
from scripts.live_backend import postgres_url
from security_admin import current_role

TABLES = {
    "Müşteriler": ("customers", ("name", "country", "contact", "email")),
    "Ürünler": ("products", ("name", "supplier", "unit", "stock_kg")),
    "Görevler": ("tasks", ("title", "owner", "due_date", "status")),
    "Siparişler": ("orders", ("reference", "customer", "product", "quantity_kg", "status")),
    "Teklifler": ("quotes", ("reference", "customer", "product", "quantity_kg", "unit_price", "currency")),
}
EDITABLE = {
    "Müşteriler": ("name", "country", "contact", "email"),
    "Ürünler": ("name", "supplier", "unit", "stock_kg"),
    "Görevler": ("title", "owner", "due_date", "status"),
    "Siparişler": ("reference", "customer", "product", "quantity_kg", "status"),
    "Teklifler": ("reference", "customer", "product", "quantity_kg", "unit_price", "currency"),
}
NUMERIC = {"stock_kg", "quantity_kg", "unit_price"}
CHOICES = {
    "unit": ("kg", "ton", "adet", "koli", "litre"),
    "currency": ("EUR", "USD", "GBP", "TRY", "TL"),
    "status": ("Taslak", "Onaylandı", "Hazırlanıyor", "Sevk Edildi", "Teslim Edildi", "İptal", "onaylandı"),
}
LABELS = {
    "name": "Ad / Ürün adı", "country": "Ülke", "contact": "İlgili kişi",
    "email": "E-posta", "supplier": "Tedarikçi", "unit": "Ölçü birimi",
    "stock_kg": "Stok miktarı (kg)", "title": "Görev",
    "owner": "Sorumlu", "due_date": "Termin tarihi",
    "status": "Durum", "reference": "Referans / Sipariş no.",
    "customer": "Müşteri", "product": "Ürün", "quantity_kg": "Miktar (kg)",
    "unit_price": "Birim fiyat", "currency": "Para birimi",
}


def valid_company(code):
    if code not in COMPANY_LABELS:
        raise ValueError("unknown_company")
    return code


def _db():
    import psycopg
    url = postgres_url()
    if not url or url == "INVALID_POSTGRES_URL":
        raise RuntimeError("demo_database_unavailable")
    return psycopg.connect(url, connect_timeout=8, sslmode="require")


def _relation(section):
    if section not in TABLES:
        raise ValueError("unknown_section")
    return TABLES[section]


def _fields(section, values):
    allowed = EDITABLE.get(section)
    if allowed is None or not isinstance(values, dict) or set(values) != set(allowed):
        raise ValueError("invalid_fields")
    clean = {}
    for key in allowed:
        value = values[key]
        if key in NUMERIC:
            try:
                value = Decimal(str(value))
            except (ValueError, TypeError, InvalidOperation):
                raise ValueError("invalid_number") from None
            if not value.is_finite() or value < 0 or value > 10**12:
                raise ValueError("invalid_number")
        else:
            value = str(value or "").strip()[:250]
            if key in CHOICES and value not in CHOICES[key]:
                raise ValueError("invalid_choice")
        clean[key] = value
    if not clean[allowed[0]]:
        raise ValueError("required_field")
    return clean


def list_records(company, section):
    valid_company(company)
    table, columns = _relation(section)
    query = (
        "SELECT id," + ",".join(columns) +
        " FROM ct_demo." + table +
        " WHERE company_code=%s ORDER BY id DESC LIMIT 500"
    )
    with _db() as conn, conn.cursor() as cur:
        cur.execute(query, (company,))
        return [dict(zip(("id",) + columns, row)) for row in cur.fetchall()]


def add_record(company, section, values):
    valid_company(company)
    table, columns = _relation(section)
    clean = _fields(section, values)
    query = (
        "INSERT INTO ct_demo." + table +
        " (company_code," + ",".join(columns) + ") VALUES (" +
        ",".join(["%s"] * (len(columns) + 1)) + ") RETURNING id"
    )
    with _db() as conn, conn.cursor() as cur:
        cur.execute(query, (company,) + tuple(clean[c] for c in columns))
        return cur.fetchone()[0]


def update_record(company, section, record_id, values):
    valid_company(company)
    table, columns = _relation(section)
    clean = _fields(section, values)
    ident = int(record_id)
    if ident <= 0:
        raise ValueError("invalid_id")
    query = (
        "UPDATE ct_demo." + table + " SET " +
        ",".join(c + "=%s" for c in columns) +
        " WHERE company_code=%s AND id=%s RETURNING id"
    )
    with _db() as conn, conn.cursor() as cur:
        cur.execute(query, tuple(clean[c] for c in columns) + (company, ident))
        return cur.fetchone() is not None


def delete_record(company, section, record_id):
    valid_company(company)
    table, _ = _relation(section)
    ident = int(record_id)
    if ident <= 0:
        raise ValueError("invalid_id")
    with _db() as conn, conn.cursor() as cur:
        cur.execute("DELETE FROM ct_demo." + table +
                    " WHERE company_code=%s AND id=%s RETURNING id",
                    (company, ident))
        return cur.fetchone() is not None


def render_four_company_demo():
    st.subheader("AS Control Tower · Dört Şirket")
    st.info("DEMO ORTAMI · Buradaki bilgiler test içindir. Gerçek ticari veri girmeyin.")
    if current_role() != "ADMIN":
        st.warning("Demo kayıt yönetimi yalnızca ADMIN rolüne açık.")
        return
    company = st.selectbox("Şirket", list(COMPANY_LABELS),
                           format_func=lambda code: COMPANY_LABELS[code],
                           key="ct_demo_company")
    section = st.selectbox("Bölüm", list(TABLES), key="ct_demo_section")
    table, columns = _relation(section)
    try:
        rows = list_records(company, section)
    except Exception:
        st.error("Demo veritabanı hazır değil veya bağlantı kurulamadı.")
        return

    st.metric("Bu şirketteki kayıt", len(rows))
    if section == "Teklifler" and rows:
        for item in rows:
            item["toplam"] = Decimal(str(item["quantity_kg"])) * Decimal(str(item["unit_price"]))
    if rows:
        import pandas as pd
        st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)
        st.download_button("Bu şirketin CSV dosyasını indir",
                           pd.DataFrame(rows).to_csv(index=False).encode("utf-8-sig"),
                           file_name=f"{company}_{table}_DEMO.csv",
                           mime="text/csv")
    else:
        st.caption("Henüz kayıt yok. Aşağıdaki formdan ekleyebilirsiniz.")

    # PDF uses only the already company-filtered rows. No unverified corporate
    # details and no cross-company lookup. Generating a PDF never writes data.
    if section in ("Teklifler", "Siparişler") and rows:
        from company_pdf_export import (
            DELIVERY, LEAD_TIME, PACKAGING, PAYMENT, generate_company_pdf,
        )
        with st.expander("📄 Seçili kayıttan PDF oluştur", expanded=False):
            selected_pdf_id = st.selectbox(
                "PDF için kayıt seç", [r["id"] for r in rows],
                format_func=lambda i: str(i) + " · " +
                str(next(r["reference"] for r in rows if r["id"] == i)),
                key=f"ct_pdf_selected_{company}_{section}",
            )
            pdf_record = next(r for r in rows if r["id"] == selected_pdf_id)
            pdf_options = {}
            if section == "Teklifler":
                left, right = st.columns(2)
                pdf_options["payment"] = left.selectbox("Ödeme vadesi", PAYMENT,
                    key=f"ct_pdf_payment_{company}_{selected_pdf_id}")
                pdf_options["delivery"] = right.selectbox("Teslim yeri", DELIVERY,
                    key=f"ct_pdf_delivery_{company}_{selected_pdf_id}")
                pdf_options["lead_time"] = left.selectbox("Teslim süresi", LEAD_TIME,
                    key=f"ct_pdf_lead_{company}_{selected_pdf_id}")
                pdf_options["packaging"] = right.selectbox("Ambalaj", PACKAGING,
                    key=f"ct_pdf_pack_{company}_{selected_pdf_id}")
                pdf_options["validity_days"] = left.number_input(
                    "Teklif geçerliliği (gün)", min_value=1, max_value=365, value=14,
                    key=f"ct_pdf_valid_{company}_{selected_pdf_id}")
                pdf_options["discount_pct"] = right.number_input(
                    "İskonto (%)", min_value=0.0, max_value=100.0, value=0.0,
                    key=f"ct_pdf_discount_{company}_{selected_pdf_id}")
                pdf_options["vat_pct"] = left.number_input(
                    "KDV (%) — oranı kontrol edin", min_value=0.0,
                    max_value=100.0, value=0.0,
                    key=f"ct_pdf_vat_{company}_{selected_pdf_id}")
                st.caption("PDF tutarları seçilen iskonto ve KDV ile hesaplanır. "
                           "KDV varsayılanı %0'dır; gerçek oranı ayrıca doğrulayın.")
            pdf_options["notes"] = st.text_area(
                "PDF notları (isteğe bağlı)", max_chars=1000,
                key=f"ct_pdf_notes_{company}_{section}_{selected_pdf_id}")
            try:
                pdf_data = generate_company_pdf(
                    company_code=company, kind=section, record=pdf_record,
                    **pdf_options)
                st.download_button(
                    "📄 " + ("Teklif PDF indir" if section == "Teklifler"
                             else "Sipariş PDF indir"),
                    data=pdf_data,
                    file_name=f"{company}_{section}_{selected_pdf_id}_DEMO.pdf",
                    mime="application/pdf",
                    key=f"ct_pdf_download_{company}_{section}_{selected_pdf_id}",
                )
            except (ValueError, RuntimeError):
                st.error("PDF oluşturulamadı. Alanları ve PDF yazı tipini kontrol edin.")

    mode = st.radio("İşlem", ("Yeni kayıt", "Düzenle", "Sil"), horizontal=True,
                    key="ct_demo_mode")
    if mode != "Yeni kayıt" and not rows:
        return
    selected = None
    if mode != "Yeni kayıt":
        selected_id = st.selectbox("Kayıt", [r["id"] for r in rows],
                                  format_func=lambda i: str(i) + " · " +
                                  str(next(r[columns[0]] for r in rows if r["id"] == i)),
                                  key="ct_demo_selected")
        selected = next(r for r in rows if r["id"] == selected_id)

    with st.form(f"ct_demo_form_{company}_{section}_{mode}"):
        values = {}
        if mode != "Sil":
            for column in columns:
                original = selected[column] if selected else None
                widget_key = f"ct_demo_{company}_{section}_{mode}_{selected['id'] if selected else 'new'}_{column}"
                label = LABELS.get(column, column)
                if column in CHOICES:
                    choices = CHOICES[column]
                    default = str(original or "")
                    values[column] = st.selectbox(
                        label, choices, index=choices.index(default) if default in choices else 0,
                        key=widget_key)
                elif column in NUMERIC:
                    values[column] = st.number_input(
                        label, min_value=0.0, value=float(original or 0),
                        key=widget_key)
                else:
                    values[column] = st.text_input(
                        label, value=str(original or ""),
                        key=widget_key)
            if section == "Teklifler":
                st.caption("Toplam tutar = Miktar (kg) × Birim fiyat. KDV hariçtir.")
        submitted = st.form_submit_button(
            {"Yeni kayıt": "Kaydet", "Düzenle": "Değişiklikleri kaydet",
             "Sil": "Demo kaydını sil"}[mode])
    if submitted:
        try:
            if mode == "Yeni kayıt":
                add_record(company, section, values)
            elif mode == "Düzenle":
                if not update_record(company, section, selected["id"], values):
                    raise ValueError("record_missing")
            else:
                if not delete_record(company, section, selected["id"]):
                    raise ValueError("record_missing")
            st.toast("Kayıt işlemi tamamlandı.", icon="✅")
            st.rerun()
        except ValueError:
            st.error("Alanları kontrol edin. İlk alan boş olamaz; tutarlar negatif olamaz.")
        except Exception:
            st.error("Kayıt işlemi tamamlanamadı; veritabanı bağlantısını kontrol edin.")
