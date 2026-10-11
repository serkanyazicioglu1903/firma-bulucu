"""Mobile ownership review panel: least authority and no implicit reads."""
import unittest
from unittest.mock import patch

import company_ownership_coverage_ui as ui

CI_URL = "postgresql://ci-user@synthetic.example.test/demo"


def valid_report(**changes):
    result = {
        "status": "ownership_structure_incomplete",
        "table_count": 26, "rls_enabled_count": 0,
        "direct_owner_count": 0, "required_nonnull_owner_count": 0,
        "missing_required_owner": tuple(ui.REVIEW_GROUPS["direct_owner_required"]),
        "nullable_required_owner": (),
        "tables_needing_design_review": (
            "customers", "product_catalog", "warehouses",
        ),
        "four_company_isolation_verified": False,
        "live_migration_approved": False,
    }
    result.update(changes)
    return result


class CompanyCoverageUiTests(unittest.TestCase):
    @patch.object(ui, "inspect_live_company_ownership")
    @patch.object(ui, "current_role", return_value="FINANCE")
    @patch.object(ui, "st")
    def test_nonadmin_cannot_view_or_connect(self, st, role, audit):
        ui.render_company_ownership_coverage_quick(CI_URL)
        st.expander.assert_not_called()
        audit.assert_not_called()

    @patch.object(ui, "inspect_live_company_ownership")
    @patch.object(ui, "current_role", return_value="ADMIN")
    @patch.object(ui, "st")
    def test_no_automatic_connection_on_render(self, st, role, audit):
        st.button.return_value = False
        ui.render_company_ownership_coverage_quick(CI_URL)
        audit.assert_not_called()
        st.error.assert_not_called()
        st.download_button.assert_not_called()

    @patch.object(ui, "inspect_live_company_ownership")
    @patch.object(ui, "current_role", return_value="ADMIN")
    @patch.object(ui, "st")
    def test_missing_connection_fails_without_query(self, st, role, audit):
        st.button.return_value = True
        ui.render_company_ownership_coverage_quick("")
        audit.assert_not_called()
        st.error.assert_called_once()

    @patch.object(ui, "inspect_live_company_ownership",
                  return_value=valid_report())
    @patch.object(ui, "current_role", return_value="ADMIN")
    @patch.object(ui, "st")
    def test_structure_incomplete_requires_review(self, st, role, audit):
        st.button.return_value = True
        ui.render_company_ownership_coverage_quick(CI_URL)
        audit.assert_called_once_with(CI_URL)
        warnings = " ".join(str(a.args[0]) for a in st.warning.call_args_list)
        self.assertIn("Şirket sahiplik kolonu eksik", warnings)
        self.assertIn("Diğer 18 tablonun", warnings)
        errors = " ".join(str(a.args[0]) for a in st.error.call_args_list)
        self.assertIn("ONAYLI DEĞİL", errors)
        st.success.assert_not_called()
        st.download_button.assert_not_called()

    @patch.object(ui, "inspect_live_company_ownership",
                  return_value=valid_report(
                      status="review_required", required_nonnull_owner_count=8,
                      direct_owner_count=8, rls_enabled_count=26,
                      missing_required_owner=(),
                  ))
    @patch.object(ui, "current_role", return_value="ADMIN")
    @patch.object(ui, "st")
    def test_full_columns_and_rls_still_not_approved(self, st, role, audit):
        st.button.return_value = True
        ui.render_company_ownership_coverage_quick(CI_URL)
        self.assertTrue(any("ONAYLI DEĞİL" in str(c.args[0])
                            for c in st.error.call_args_list))
        st.success.assert_not_called()

    @patch.object(ui, "inspect_live_company_ownership",
                  return_value=valid_report(status="schema_mismatch"))
    @patch.object(ui, "current_role", return_value="ADMIN")
    @patch.object(ui, "st")
    def test_incomplete_metadata_never_renders_approval(self, st, role, audit):
        st.button.return_value = True
        ui.render_company_ownership_coverage_quick(CI_URL)
        st.error.assert_called_once()
        st.success.assert_not_called()


if __name__ == "__main__":
    unittest.main()
