"""UI authorization and no-side-effects tests for PostgreSQL 360."""
import unittest
from unittest.mock import patch

import postgres_workspace as workspace


class Postgres360UiTests(unittest.TestCase):
    @patch.object(workspace, "read_operational_counts")
    @patch.object(workspace, "read_operational_workspace")
    @patch.object(workspace, "current_role", return_value="VIEWER")
    @patch.object(workspace, "st")
    def test_non_admin_cannot_query_postgres(self, st, _role, rows, counts):
        workspace.render_postgres_workspace()
        st.error.assert_called_once()
        counts.assert_not_called()
        rows.assert_not_called()
        self.assertFalse(st.secrets.get.called)

    @patch.object(workspace, "read_operational_counts")
    @patch.object(workspace, "read_operational_workspace")
    @patch.object(workspace, "current_role", return_value="ADMIN")
    @patch.object(workspace, "st")
    def test_admin_without_secret_does_not_query_postgres(
        self, st, _role, rows, counts,
    ):
        st.secrets.get.return_value = ""
        workspace.render_postgres_workspace()
        st.warning.assert_called_once()
        counts.assert_not_called()
        rows.assert_not_called()

    @patch.object(workspace, "read_operational_counts", return_value=(
        "ok", {"customers": 0, "purchase_orders": 0, "inventory_lots": 0, "quality_cases": 0},
    ))
    @patch.object(workspace, "read_operational_workspace", return_value=(
        "ok", [{"id": 123, "name": "FICTIONAL CI CUSTOMER"}],
    ))
    @patch.object(workspace, "current_role", return_value="ADMIN")
    @patch.object(workspace, "st")
    def test_admin_reads_only_after_button_press(self, st, _role, rows, counts):
        st.secrets.get.return_value = "postgresql://fake-connection"
        st.button.return_value = False
        st.selectbox.return_value = "Müşteriler"
        workspace.render_postgres_workspace()
        counts.assert_not_called()
        rows.assert_not_called()
        self.assertFalse(st.dataframe.called)

        st.button.side_effect = [False, True]
        workspace.render_postgres_workspace()
        rows.assert_called_once_with(
            "postgresql://fake-connection", "Müşteriler"
        )
        self.assertTrue(st.dataframe.called)
        counts.assert_not_called()


if __name__ == "__main__":
    unittest.main()
