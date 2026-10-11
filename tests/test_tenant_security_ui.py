"""Admin-only API/RLS view is on-demand; no records or secret downloads."""
import unittest
from unittest.mock import patch

import tenant_security_ui as ui

URL="postgresql://synthetic-ci@example.test/db"


def report(**overrides):
    base = {
        "status": "tenant_migration_incomplete",
        "total_tables": 26, "rls_enabled": 0,
        "owner_columns": 0, "registry_tables": 0,
        "api_direct_access": {
            "anon": 0, "authenticated": 0, "service_role": 0,
        },
        "api_direct_writes": {
            "anon": 0, "authenticated": 0, "service_role": 0,
        },
        "current_session_elevated": False,
        "ready_for_production_cutover": False,
    }
    base.update(overrides)
    return base


class CompanySecurityUiTests(unittest.TestCase):
    @patch.object(ui,"inspect_company_access_security")
    @patch.object(ui,"current_role",return_value="SALES")
    @patch.object(ui,"st")
    def test_nonadmin_never_sees_or_runs_audit(self,st,role,query):
        ui.render_company_access_security_quick(URL)
        query.assert_not_called()
        st.expander.assert_not_called()

    @patch.object(ui,"inspect_company_access_security")
    @patch.object(ui,"current_role",return_value="ADMIN")
    @patch.object(ui,"st")
    def test_admin_audit_is_only_on_explicit_click(self,st,role,query):
        st.button.return_value=False
        ui.render_company_access_security_quick(URL)
        st.expander.assert_called_once()
        query.assert_not_called()
        st.download_button.assert_not_called()

    @patch.object(ui,"inspect_company_access_security",return_value=report())
    @patch.object(ui,"current_role",return_value="ADMIN")
    @patch.object(ui,"st")
    def test_no_api_grants_does_not_claim_public_exposure_or_go_live(
        self,st,role,query,
    ):
        st.button.return_value=True
        ui.render_company_access_security_quick(URL)
        query.assert_called_once_with(URL)
        messages = " ".join(
            str(c.args[0]) for c in st.warning.call_args_list
        )
        self.assertIn("doğrudan tablo erişim izni tespit edilmedi",messages)
        self.assertIn("RLS bütün uygulama tablolarında açık değil",messages)
        self.assertTrue(any(
            "ONAYLI DEĞİL" in str(c.args[0])
            for c in st.error.call_args_list
        ))
        st.success.assert_not_called()

    @patch.object(ui,"inspect_company_access_security",return_value=report(
        status="api_permissions_review",
        api_direct_access={"anon":2,"authenticated":0,"service_role":0},
        api_direct_writes={"anon":1,"authenticated":0,"service_role":0},
    ))
    @patch.object(ui,"current_role",return_value="ADMIN")
    @patch.object(ui,"st")
    def test_api_grant_is_flagged_as_risk(self,st,role,query):
        st.button.return_value=True
        ui.render_company_access_security_quick(URL)
        self.assertTrue(any(
            "doğrudan tablo izni tespit" in str(c.args[0])
            for c in st.error.call_args_list
        ))

    @patch.object(ui,"inspect_company_access_security")
    @patch.object(ui,"current_role",return_value="ADMIN")
    @patch.object(ui,"st")
    def test_missing_db_blocks_without_query(self,st,role,query):
        st.button.return_value=True
        ui.render_company_access_security_quick("")
        query.assert_not_called()
        st.error.assert_called_once()


if __name__=="__main__":
    unittest.main()
