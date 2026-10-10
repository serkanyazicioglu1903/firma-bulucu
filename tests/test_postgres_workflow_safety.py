import pytest
from scripts.postgres_workflow import validate_test_url
from scripts.build_pg_schema import generate


@pytest.mark.parametrize('url',[
    'postgresql://u:p@remote.example/ct_test',
    'postgresql://u:p@localhost/production',
    'postgresql://u:p@localhost/ct_test?options=-csearch_path%3Dpublic',
    'postgresql://u:p@localhost/ct_test?hostaddr=203.0.113.1',
    'dbname=ct_test',
])
def test_postgres_acceptance_refuses_non_test_targets(url):
    with pytest.raises(ValueError):
        validate_test_url(url)


def test_generated_schema_includes_adjustment_and_quote_guards():
    ddl,tables=generate()
    assert {'workflow_orders','workflow_deliveries','workflow_costs','workflow_returns',
            'finance_reversals','workflow_reconciliations'}.issubset(tables)
    assert 'credit_amount' in ddl
    assert 'CREATE TRIGGER workflow_quote_frozen' in ddl
    assert 'SET search_path FROM CURRENT' in ddl
