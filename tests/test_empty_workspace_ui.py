"""Empty-workspace Streamlit smoke test in a separate, disposable process.

Separate interpreter avoids leaking Streamlit form/session contexts from other
unittest cases. The database is confined to a temporary directory.
"""
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class EmptyWorkspaceUITests(unittest.TestCase):
    def test_empty_workspace_starts_without_seed_or_crash(self):
        with tempfile.TemporaryDirectory() as directory:
            db = Path(directory) / "empty_workspace.db"
            env = dict(os.environ)
            env["AS_CONTROL_TOWER_DB_PATH"] = str(db)
            env.pop("AS_CONTROL_TOWER_DEMO_SEED", None)
            script = """
import sqlite3
from pathlib import Path
from streamlit.testing.v1 import AppTest
app = AppTest.from_file("app.py", default_timeout=60)
app.session_state["ct_user"] = {
    "username": "isolated-admin",
    "display_name": "Isolated Admin",
    "role": "ADMIN",
}
app.session_state["ct_session_id"] = "isolated-session"
app.run()
assert not app.exception, str(app.exception)
with sqlite3.connect(Path(__import__("os").environ["AS_CONTROL_TOWER_DB_PATH"])) as conn:
    for table in ("customers", "product_catalog", "warehouses", "purchase_orders"):
        assert conn.execute("SELECT COUNT(*) FROM " + table).fetchone()[0] == 0, table
print("EMPTY_WORKSPACE_OK")
"""
            result = subprocess.run(
                [sys.executable, "-c", script],
                cwd=ROOT,
                env=env,
                capture_output=True,
                text=True,
                timeout=90,
                check=False,
            )
            self.assertEqual(
                result.returncode, 0,
                (result.stdout + "\n" + result.stderr)[-4500:],
            )
            self.assertIn("EMPTY_WORKSPACE_OK", result.stdout)


if __name__ == "__main__":
    unittest.main()
