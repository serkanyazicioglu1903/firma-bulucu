"""Credential-safe, read-only Supabase connectivity tests."""
import security_admin


def test_missing_and_placeholder_urls():
    assert security_admin.test_postgres_connection("")[1] == "missing"
    assert security_admin.test_postgres_connection("not-a-url")[1] == "invalid_url"
    assert security_admin.test_postgres_connection(
        "postgresql://postgres:[YOUR-PASSWORD]@example.com:5432/postgres"
    )[1] == "placeholder"


def test_read_only_query(monkeypatch):
    class Cursor:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def execute(self, sql):
            assert sql == "SELECT 1"

        def fetchone(self):
            return (1,)

    class Conn:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def cursor(self):
            return Cursor()

    def connect(url, **kwargs):
        assert url.startswith("postgresql://")
        assert kwargs == {"connect_timeout": 8, "sslmode": "require"}
        return Conn()

    import psycopg
    monkeypatch.setattr(psycopg, "connect", connect)
    assert security_admin.test_postgres_connection(
        "postgresql://user:secret@host.example:5432/postgres"
    ) == (True, "ok")


def test_connection_errors_do_not_expose_credentials(monkeypatch):
    import psycopg

    def fail(*args, **kwargs):
        raise RuntimeError("postgresql://user:super-secret@host.example/postgres")

    monkeypatch.setattr(psycopg, "connect", fail)
    result = security_admin.test_postgres_connection(
        "postgresql://user:super-secret@host.example/postgres"
    )
    assert result == (False, "connection_failed")
    assert "super-secret" not in repr(result)
