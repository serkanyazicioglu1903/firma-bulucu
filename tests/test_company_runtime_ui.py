from pathlib import Path
from unittest.mock import patch
from streamlit.testing.v1 import AppTest
from scripts.group_company_catalog import COMPANY_LABELS
from scripts import company_runtime as rt
import company_runtime_ui as ui


def test_invalid_runtime_blocks_legacy(monkeypatch):
    monkeypatch.setenv(rt.MODE_KEY,'TYPO')
    app=AppTest.from_file(str(Path(__file__).resolve().parents[1]/'app.py'),default_timeout=30)
    app.session_state['ct_user']={'username':'ci-admin','role':'ADMIN'}
    app.session_state['ct_session_id']='test'
    app.run()
    assert not app.exception
    assert not app.tabs
    assert any('geçersiz' in e.value for e in app.error)


def test_form_posts_to_selected_company_and_retries_same_id():
    captured=[]
    def request(state,company,**kwargs):
        captured.append((company,kwargs))
        return 'ok',17
    with patch.object(ui,'verified_company_principal',return_value='alpha'), patch.object(ui,'current_role',return_value='ADMIN'), patch.object(ui,'runtime_mode',return_value=rt.WRITE_MODE), patch.object(ui,'execute_request',side_effect=request):
        app=AppTest.from_string('from company_runtime_ui import render_company_runtime\nrender_company_runtime()').run()
        assert not app.exception
        app.text_input(key='runtime_field_name').set_value('Synthetic customer')
        app.button[-1].click().run()
        assert not app.exception
        assert captured[-1][0]==next(iter(COMPANY_LABELS))
        assert captured[-1][1]['inputs']['name']=='Synthetic customer'
        app.run()
        assert not app.text_input
        assert len(captured)==1


def test_company_change_clears_form_values():
    with patch.object(ui,'verified_company_principal',return_value='alpha'), patch.object(ui,'current_role',return_value='ADMIN'), patch.object(ui,'runtime_mode',return_value=rt.WRITE_MODE):
        app=AppTest.from_string('from company_runtime_ui import render_company_runtime\nrender_company_runtime()').run()
        app.text_input(key='runtime_field_name').set_value('Private draft')
        old=app.session_state['runtime_request_id']
        app.selectbox(key='runtime_company').select(tuple(COMPANY_LABELS)[1]).run()
        assert not app.exception
        assert app.text_input(key='runtime_field_name').value==''
        assert app.session_state['runtime_request_id']!=old
