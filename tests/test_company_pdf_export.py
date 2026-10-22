from decimal import Decimal

import pytest

from company_pdf_export import generate_company_pdf


def quote():
    return {"id": 1, "reference": "Q-25", "customer": "Ülker",
            "product": "Süt tozu", "quantity_kg": Decimal("250000"),
            "unit_price": Decimal("2.40"), "currency": "EUR"}


def terms():
    return {"payment": "30 gün", "delivery": "Depodan",
            "lead_time": "2 hafta", "packaging": "25 kg torba"}


def test_pdf_quote_is_generated_without_inventing_corporate_details():
    data = generate_company_pdf(company_code="AS_FOOD_GLOBAL", kind="Teklifler",
                                record=quote(), **terms())
    assert data.startswith(b"%PDF")
    assert len(data) > 2000


def test_pdf_order_has_no_invented_price():
    data = generate_company_pdf(company_code="AS_ILERI_GIDA", kind="Siparişler",
        record={"reference": "PO-2", "customer": "UNO", "product": "Lesitin",
                "quantity_kg": Decimal("200"), "status": "Onaylandı"})
    assert data.startswith(b"%PDF")


def test_rejects_unknown_company_and_invalid_currency():
    with pytest.raises(ValueError):
        generate_company_pdf(company_code="OTHER", kind="Teklifler",
                             record=quote(), **terms())
    bad = quote()
    bad["currency"] = "FAKE"
    with pytest.raises(ValueError):
        generate_company_pdf(company_code="AS_FOOD_GLOBAL", kind="Teklifler",
                             record=bad, **terms())


def test_rejects_invalid_discounts_and_missing_terms():
    with pytest.raises(ValueError):
        generate_company_pdf(company_code="AS_FOOD_GLOBAL", kind="Teklifler",
                             record=quote(), **terms(), discount_pct=101)
    with pytest.raises(ValueError):
        generate_company_pdf(company_code="AS_FOOD_GLOBAL", kind="Teklifler",
                             record=quote())
