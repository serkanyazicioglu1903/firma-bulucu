"""Streamlit smoke test against an isolated, initially empty SQLite database."""
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from streamlit.testing.v1 import AppTest
import control_tower as ct


class EmptyWorkspaceUITests(unittest.TestCase):
    def test_empty_workspace_starts_without_seed_or_crash(self):
        with tempfile.TemporaryDirectory() as directory:
            test_db = Path(directory) / "empty_workspace.db"
            with patch.dict(os.environ, {"AS_CONTROL_TOWER_DEMO_SEED": ""}):
                with patch.object(ct, "DB_PATH", test_db):
                    app = AppTest.from_file(
                        Path(__file__).resolve().parents[1] / "app.py",
                        default_timeout=60,
                    )
                    app.session_state["ct_user"] = {
                        "username": "isolated-admin",
                        "display_name": "Isolated Admin",
                        "role": "ADMIN",
                    }
                    app.session_state["ct_session_id"] = "isolated-session"
                    app.run()
                    self.assertFalse(app.exception, str(app.exception))
                    with ct.get_conn() as conn:
                        for table in (
                            "customers", "product_catalog", "warehouses",
                            "purchase_orders",
                        ):
                            with self.subTest(table=table):
                                self.assertEqual(
                                    conn.execute(
                                        f"SELECT COUNT(*) FROM {table}"
                                    ).fetchone()[0], 0
                                )


if __name__ == "__main__":
    unittest.main()
