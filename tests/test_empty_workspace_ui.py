"""Smoke-test a brand-new empty Control Tower workspace with no demo seed.

The app is executed through Streamlit's test harness, not a live service.
All SQLite writes are redirected to a temporary test-only path.
"""
from streamlit.testing.v1 import AppTest
import control_tower as ct


def test_empty_workspace_starts_without_seed_or_crash(monkeypatch, tmp_path):
    monkeypatch.delenv("AS_CONTROL_TOWER_DEMO_SEED", raising=False)
    test_db = tmp_path / "empty_workspace.db"
    monkeypatch.setattr(ct, "DB_PATH", test_db)

    app = AppTest.from_file(
        str(__import__("pathlib").Path(__file__).resolve().parents[1] / "app.py"),
        default_timeout=60,
    )
    app.session_state["ct_user"] = {
        "username": "isolated-admin",
        "display_name": "Isolated Admin",
        "role": "ADMIN",
    }
    app.session_state["ct_session_id"] = "isolated-session"
    app.run()
    assert not app.exception, str(app.exception)

    with ct.get_conn() as conn:
        for table in ("customers", "product_catalog", "warehouses", "purchase_orders"):
            assert conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] == 0
