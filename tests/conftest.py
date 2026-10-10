"""Every pytest test gets an isolated database, never the user's application file."""
import pytest
import control_tower


@pytest.fixture(autouse=True)
def isolated_db(monkeypatch, tmp_path):
    monkeypatch.setattr(control_tower, 'DB_PATH', tmp_path / 'control_tower_test.db')
    monkeypatch.setenv('CONTROL_TOWER_PASSWORD', 'isolated-test-password')
    monkeypatch.setenv('APP_USERS_JSON', '')
