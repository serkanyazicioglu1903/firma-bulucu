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
    app.session_state["ct_user"] = {
        "username": "ci-admin",
        "display_name": "CI Admin",
        "role": "ADMIN",
    }
    app.session_state["ct_session_id"] = "ci-session"
    app.run()
    assert not app.exception

    product_box = find_by_key(app.selectbox, "intel_product_select")
    app = product_box.select("Fat Powder FI FP 80 PR 01").run()
    assert not app.exception

    with sqlite3.connect(db_path) as conn:
        product_id = conn.execute(
            "SELECT id FROM product_catalog WHERE name='Fat Powder FI FP 80 PR 01'"
        ).fetchone()[0]
        visible_customer_ids = {
            int(row[0])
            for row in conn.execute(
                "SELECT id FROM customers WHERE name IN ('Ülker / Pladis','Pakmaya')"
            ).fetchall()
        }

    customer_box = find_by_key(app.selectbox, f"intel_product_rec_{product_id}")
    # The selector may default to either scored recommendation, but it must
    # never retain a stale customer outside the currently visible candidates.
    assert int(customer_box.value) in visible_customer_ids
