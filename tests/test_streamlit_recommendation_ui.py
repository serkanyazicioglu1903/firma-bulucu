import sqlite3
from pathlib import Path

from streamlit.testing.v1 import AppTest


def find_by_key(elements, key):
    for element in elements:
        if getattr(element, "key", None) == key:
            return element
    raise AssertionError(f"Widget not found: {key}")


def test_product_customer_selector_does_not_keep_stale_customer():
    db_path = Path("as_control_tower.db")
    if db_path.exists():
        db_path.unlink()

    app_path = Path(__file__).resolve().parents[1] / "app.py"
    app = AppTest.from_file(app_path, default_timeout=60)
    app.run()
    assert not app.exception

    product_box = find_by_key(app.selectbox, "intel_product_select")
    app = product_box.select("Fat Powder FI FP 80 PR 01").run()
    assert not app.exception

    with sqlite3.connect(db_path) as conn:
        pakmaya_id = conn.execute(
            "SELECT id FROM customers WHERE name='Pakmaya'"
        ).fetchone()[0]
        product_id = conn.execute(
            "SELECT id FROM product_catalog WHERE name='Fat Powder FI FP 80 PR 01'"
        ).fetchone()[0]

    customer_box = find_by_key(app.selectbox, f"intel_product_rec_{product_id}")
    assert int(customer_box.value) == int(pakmaya_id)
