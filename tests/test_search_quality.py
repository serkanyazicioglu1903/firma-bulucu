import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import app


def test_acquisition_rejects_restaurant_even_on_preferred_marketplace():
    ok, sale, maker = app.acq_candidate_ok(
        "Restaurant business for sale",
        "Owner retiring, fully equipped restaurant and cafe",
        "",
        "https://www.dub.de/de/unternehmen-kaufen/expose/test",
        "Almanya",
        "Gıda hammaddesi / Food ingredients",
    )
    assert sale
    assert not ok


def test_acquisition_preferred_listing_needs_sector_match():
    ok, sale, maker = app.acq_candidate_ok(
        "Unternehmensnachfolge Lebensmittelzutaten",
        "Herstellerunabhängiger B2B Anbieter von Lebensmittelrohstoffen zu verkaufen",
        "",
        "https://www.dub.de/de/unternehmen-kaufen/expose/food",
        "Almanya",
        "Gıda hammaddesi / Food ingredients",
    )
    assert sale
    assert ok


def test_generic_acquisition_requires_manufacturing_signal():
    ok, sale, maker = app.acq_candidate_ok(
        "Food ingredients business for sale",
        "Distributor of food ingredients; owner retiring",
        "",
        "https://example-food-distributor.com/sale",
        "İngiltere",
        "Gıda hammaddesi / Food ingredients",
    )
    assert sale
    assert not maker
    assert not ok


def test_strong_factory_evidence_confirms_manufacturer():
    status, score = app.supplier_manufacturer_status(
        "Dextrose Monohydrate",
        "Dextrose Monohydrate | Example Ingredients",
        "",
        (
            "We produce dextrose monohydrate in our manufacturing facility. "
            "Our plant operates food-grade production lines."
        ),
        "https://example.com/products/dextrose-monohydrate",
    )
    assert status == "confirmed"
    assert score >= 45


def test_trader_signal_is_not_promoted_to_manufacturer():
    status, score = app.supplier_manufacturer_status(
        "Dextrose Monohydrate",
        "Dextrose Monohydrate supplier",
        "",
        (
            "We are a trading company and broker for dextrose monohydrate. "
            "Our partner factory supplies multiple origins."
        ),
        "https://example.com/dextrose",
    )
    assert status == "unclear"


def test_sales_email_prefers_export_and_rejects_procurement():
    value = app.choose_sales_email(
        "procurement@example.com; export@example.com; info@example.com"
    )
    assert value == "export@example.com"
