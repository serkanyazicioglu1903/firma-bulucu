import json
import tomllib
from unittest.mock import patch

from streamlit.testing.v1 import AppTest
import private_login_setup_ui as ui


def test_only_serkan_admin_can_prepare_settings():
    for user in [None, {'username':'serkan','role':'VIEWER'}, {'username':'other','role':'ADMIN'}]:
        with patch.object(ui, 'current_user', return_value=user):
            app = AppTest.from_string('from private_login_setup_ui import render_private_login_setup\nrender_private_login_setup()')
            app.session_state['runtime_private_login_settings'] = 'synthetic-secret'
            app.run()
            assert not app.exception
            assert not app.text_input
            assert not app.code
            assert 'runtime_private_login_settings' not in app.session_state


def test_settings_are_session_local_and_clearable():
    with patch.object(ui, 'current_user', return_value={'username':'serkan','role':'ADMIN'}):
        app = AppTest.from_string('from private_login_setup_ui import render_private_login_setup\nrender_private_login_setup()').run()
        app.text_input[0].set_value('Synthetic-mobile-password-123')
        app.text_input[1].set_value('Synthetic-mobile-password-123')
        app.button[0].click().run()
        assert not app.exception
        settings = tomllib.loads(app.code[0].value)
        assert set(settings) == {'APP_USERS_JSON','CT_COMPANY_SESSION_SIGNING_KEY'}
        assert json.loads(settings['APP_USERS_JSON'])['users'][0]['username'] == 'serkan'
        assert 'Synthetic-mobile-password-123' not in app.code[0].value
        app.button(key='runtime_setup_clear').click().run()
        assert not app.code
        assert 'runtime_private_login_settings' not in app.session_state


def test_mismatch_clears_previously_prepared_settings():
    with patch.object(ui, 'current_user', return_value={'username':'serkan','role':'ADMIN'}):
        app = AppTest.from_string('from private_login_setup_ui import render_private_login_setup\nrender_private_login_setup()').run()
        app.session_state['runtime_private_login_settings'] = 'synthetic-old-settings'
        app.text_input[0].set_value('Synthetic-mobile-password-123')
        app.text_input[1].set_value('Different-mobile-password-123')
        app.button[0].click().run()
        assert not app.exception
        assert app.error
        assert not app.code
