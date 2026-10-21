import json
from unittest.mock import patch, MagicMock
from scripts.postgres_scoped_company_write_rehearsal import ScopedWriteDenied
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


def test_direct_control_tower_route_never_opens_shared_connection():
    import control_tower as ct
    with patch.object(rt,'runtime_mode',return_value=rt.READ_MODE), patch.object(ct,'postgres_url') as shared, patch.object(ct,'_render_control_tower_interface') as screen:
        ct.render_control_tower()
        shared.assert_not_called()
        screen.assert_called_once_with()


def test_saved_quote_rejects_zero_price_preview_without_insert():
    cur = MagicMock()
    cur.fetchone.side_effect = [(7,), ('AS_ILERI_GIDA',)]
    inputs = {
        'quantity_kg': 1000, 'buy_price_per_kg': 2,
        'buy_currency': 'EUR', 'buy_fx_to_base': 1,
        'base_currency': 'EUR', 'sell_price_per_kg': 0,
        'sell_currency': 'EUR', 'sell_fx_to_base': 1,
    }
    with pytest.raises(ScopedWriteDenied) as exc:
        rt.create_quote(cur, 1, customer_id=7, product_name='Test product', **inputs)
    assert exc.value.code == 'sale_price_required'
    assert not any('INSERT INTO ct_app.quotes' in str(c.args[0]) for c in cur.execute.call_args_list)


def test_saved_quote_with_positive_price_can_be_invoiced_later():
    cur = MagicMock()
    cur.fetchone.side_effect = [(7,), ('AS_ILERI_GIDA',), (123,)]
    inputs = {
        'quantity_kg': 1000, 'buy_price_per_kg': 2,
        'buy_currency': 'EUR', 'buy_fx_to_base': 1,
        'base_currency': 'EUR', 'sell_price_per_kg': 3,
        'sell_currency': 'EUR', 'sell_fx_to_base': 1,
    }
    ident = rt.create_quote(cur, 1, customer_id=7, product_name='Test product', **inputs)
    assert ident == 123
    insert_calls = [c for c in cur.execute.call_args_list
                    if 'INSERT INTO ct_app.quotes' in str(c.args[0])]
    assert len(insert_calls) == 1
    assert 'calculation_snapshot' in insert_calls[0].args[0]
    assert '3000' in insert_calls[0].args[1][-1]
