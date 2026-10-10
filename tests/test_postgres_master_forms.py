"""PostgreSQL master form rollout is disabled by default and ADMIN-only."""
import os
import unittest
from unittest.mock import patch

import postgres_master_forms as forms

URL = "postgresql://fictional-only"


class PostgresMasterFormTests(unittest.TestCase):
    def test_default_flags_disable_live_write_ui(self):
        with patch.dict(os.environ, {}, clear=True):
            self.assertFalse(forms.postgres_master_write_enabled())

    def test_requires_both_independent_server_flags(self):
        with patch.dict(os.environ, {forms.UI_FLAG: "1", forms.ENGINE_FLAG: "0"}):
            self.assertFalse(forms.postgres_master_write_enabled())
        with patch.dict(os.environ, {forms.UI_FLAG: "0", forms.ENGINE_FLAG: "1"}):
            self.assertFalse(forms.postgres_master_write_enabled())
        with patch.dict(os.environ, {
            forms.UI_FLAG: "1", forms.ENGINE_FLAG: "1",
            "CT_LOCAL_POSTGRES_TEST": "1",
        }):
            self.assertFalse(forms.postgres_master_write_enabled())
        with patch.dict(os.environ, {
            forms.UI_FLAG: "1", forms.ENGINE_FLAG: "1",
            "CT_LOCAL_POSTGRES_TEST": "0",
        }):
            self.assertTrue(forms.postgres_master_write_enabled())

    @patch.object(forms, "create_customer")
    @patch.object(forms, "create_product")
    @patch.object(forms, "create_warehouse")
    @patch.object(forms, "current_role", return_value="VIEWER")
    @patch.object(forms, "st")
    def test_unauthorized_role_cannot_render_forms_or_write(
        self, st, _role, warehouse, product, customer,
    ):
        forms.render_postgres_master_forms(URL)
        st.error.assert_called_once()
        st.form.assert_not_called()
        customer.assert_not_called()
        product.assert_not_called()
        warehouse.assert_not_called()

    @patch.object(forms, "create_customer")
    @patch.object(forms, "create_product")
    @patch.object(forms, "create_warehouse")
    @patch.object(forms, "current_user", return_value={"username": "test-admin"})
    @patch.object(forms, "current_role", return_value="ADMIN")
    @patch.object(forms, "st")
    def test_disabled_admin_cannot_render_forms_or_write(
        self, st, _role, _user, warehouse, product, customer,
    ):
        with patch.dict(os.environ, {}, clear=True):
            forms.render_postgres_master_forms(URL)
        st.info.assert_called_once()
        st.form.assert_not_called()
        customer.assert_not_called()
        product.assert_not_called()
        warehouse.assert_not_called()

    @patch.object(forms, "create_customer")
    @patch.object(forms, "create_product")
    @patch.object(forms, "create_warehouse")
    @patch.object(forms, "current_user", return_value={"username": "ci-admin"})
    @patch.object(forms, "current_role", return_value="ADMIN")
    @patch.object(forms, "st")
    def test_button_without_per_form_consent_cannot_write(
        self, st, _role, _user, warehouse, product, customer,
    ):
        st.form_submit_button.side_effect = [True, True, True]
        st.checkbox.return_value = False
        with patch.dict(os.environ, {
            forms.UI_FLAG: "1", forms.ENGINE_FLAG: "1",
            "CT_LOCAL_POSTGRES_TEST": "0",
        }):
            forms.render_postgres_master_forms(URL)
        self.assertEqual(st.warning.call_count, 4)
        customer.assert_not_called()
        product.assert_not_called()
        warehouse.assert_not_called()

    @patch.object(forms, "create_customer", return_value=("ok", 111))
    @patch.object(forms, "create_product", return_value=("ok", 222))
    @patch.object(forms, "create_warehouse", return_value=("ok", 333))
    @patch.object(forms, "current_user", return_value={"username": "ci-admin"})
    @patch.object(forms, "current_role", return_value="ADMIN")
    @patch.object(forms, "st")
    def test_authorized_confirmed_forms_pass_actor_and_role(
        self, st, _role, _user, warehouse, product, customer,
    ):
        st.form_submit_button.side_effect = [True, True, True]
        st.checkbox.return_value = True
        st.text_input.side_effect = [
            "CI CUSTOMER", "Türkiye", "Bisküvi",
            "CI PRODUCT", "CI SUPPLIER", "Ingredient",
            "CI WAREHOUSE", "Istanbul",
        ]
        st.selectbox.return_value = "Normal Depo"
        with patch.dict(os.environ, {
            forms.UI_FLAG: "1", forms.ENGINE_FLAG: "1",
            "CT_LOCAL_POSTGRES_TEST": "0",
        }):
            forms.render_postgres_master_forms(URL)
        customer.assert_called_once_with(
            URL, "ADMIN", "CI CUSTOMER", country="Türkiye",
            sector="Bisküvi", actor="ci-admin",
        )
        product.assert_called_once_with(
            URL, "ADMIN", "CI PRODUCT", "CI SUPPLIER",
            category="Ingredient", actor="ci-admin",
        )
        warehouse.assert_called_once_with(
            URL, "ADMIN", "CI WAREHOUSE", city="Istanbul",
            warehouse_type="Normal Depo", actor="ci-admin",
        )
        self.assertEqual(st.success.call_count, 3)


if __name__ == "__main__":
    unittest.main()
