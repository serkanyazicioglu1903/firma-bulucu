import json
from unittest.mock import patch
import pytest
from scripts import company_runtime as rt
import security_admin as auth


def test_invalid_rosters_never_fall_back_to_shared_admin():
    for raw in ('bad-json','[]','{}',json.dumps([{'username':'a','enabled':'false'}]), json.dumps([{'username':'a'},{'username':'A'}])):
        with patch.object(auth,'_secret',side_effect=lambda k,d='':raw if k=='APP_USERS_JSON' else 'legacy-secret'):
            assert auth.load_users()==[]


def test_disabled_mode_never_connects():
    with patch.object(rt,'runtime_mode',return_value='disabled'), patch('psycopg.connect') as conn:
        assert rt.execute_request({},'AS_ILERI')[0]=='disabled'
        conn.assert_not_called()


def test_readonly_blocks_mutation_before_credentials():
    from scripts.group_company_catalog import COMPANY_LABELS
    with patch.object(rt,'runtime_mode',return_value=rt.READ_MODE), patch.object(rt,'verified_company_principal',return_value='alpha'), patch.object(rt,'_account_connection') as credentials:
        assert rt.execute_request({},next(iter(COMPANY_LABELS)),operation='create_customer')[0]=='read_only'
        credentials.assert_not_called()


@pytest.mark.parametrize('role,url', [
    ('postgres','postgresql://postgres:fake@host/db'),
    ('ct_alpha','postgresql://ct_beta:fake@host/db'),
    ('ct_alpha','postgresql://ct_alpha:fake@host/db?sslmode=disable'),
])
def test_unsafe_connections_rejected(role,url):
    with patch.object(rt,'_secret',return_value=json.dumps({'alpha':{'role':role,'url':url}})):
        assert rt._account_connection('alpha') is None


def test_shared_database_role_rejected():
    entry={'role':'ct_alpha','url':'postgresql://ct_alpha:fake@host/db'}
    with patch.object(rt,'_secret',return_value=json.dumps({'alpha':entry,'beta':entry})):
        assert rt._account_connection('alpha') is None


def test_invalid_mode_no_legacy_downgrade(monkeypatch):
    monkeypatch.setenv(rt.MODE_KEY,rt.WRITE_MODE)
    with patch.object(rt,'_secret',return_value=rt.READ_MODE):
        assert rt.runtime_mode()=='invalid'
