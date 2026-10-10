import pytest
import database


def test_backend_is_explicit_and_never_uses_generic_url(monkeypatch, tmp_path):
    monkeypatch.setenv('DATABASE_URL', 'postgresql://do-not-connect/production')
    with database.connect(tmp_path/'local.db') as conn:
        assert not isinstance(conn, database.PostgresConnection)
    monkeypatch.setenv('AS_CONTROL_TOWER_BACKEND', 'postgres')
    monkeypatch.delenv('AS_CONTROL_TOWER_POSTGRES_URL', raising=False)
    with pytest.raises(ValueError):
        database.connect(tmp_path/'local.db')
    monkeypatch.setenv('AS_CONTROL_TOWER_BACKEND', 'typo')
    with pytest.raises(ValueError):
        database.connect(tmp_path/'local.db')


def test_parser_preserves_literals_and_parameters():
    sql = database.postgres_sql("SELECT '?' AS question, '__CT_BIND_PARAMETER__' AS marker FROM tasks WHERE title LIKE '%a?%' AND id=?")
    assert "'?'" in sql
    assert "'__CT_BIND_PARAMETER__'" in sql
    assert "'%%a?%%'" in sql
    assert sql.count('%s') == 1


def test_report_dialect():
    sql = database.postgres_sql("SELECT MAX(a,0),MIN(a,b),MAX(a),date('now'),julianday(?) - julianday(NULLIF(d,'')) FROM tasks")
    assert 'GREATEST' in sql and 'LEAST' in sql and 'MAX(a)' in sql
    assert 'CURRENT_DATE' in sql and 'CT_JULIANDAY' in sql


@pytest.mark.parametrize('schema', ['public','pg_catalog','information_schema','evil;drop table customers','other.schema'])
def test_pg_schema_validation(monkeypatch,schema):
    monkeypatch.setenv('AS_CONTROL_TOWER_POSTGRES_URL','postgresql://localhost/ct_test')
    monkeypatch.setenv('AS_CONTROL_TOWER_POSTGRES_SCHEMA',schema)
    with pytest.raises(ValueError):
        database.pg_config()


@pytest.mark.parametrize('sql', ['SELECT 1; DELETE FROM customers', 'DROP TABLE customers', 'PRAGMA table_info(customers)'])
def test_application_parser_rejects_schema_changes_and_multiple_statements(sql):
    with pytest.raises(ValueError):
        database.postgres_sql(sql)


def test_postgres_round_uses_numeric_overload():
    assert 'CAST(SUM(amount) AS DECIMAL)' in database.postgres_sql('SELECT ROUND(SUM(amount),2) FROM payables')
