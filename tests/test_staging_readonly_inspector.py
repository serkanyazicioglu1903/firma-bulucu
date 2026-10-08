"""Tests for read-only PostgreSQL staging introspection. No real DB connection."""
import sys
import types
import unittest
from unittest.mock import patch

from security_admin import inspect_postgres_staging


class FakeCursor:
    def __init__(self):
        self.calls = []

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False

    def execute(self, sql, params=None):
        self.calls.append((sql, params))

    def fetchall(self):
        return [("customers",), ("migration_check",)]


class FakeConnection:
    def __init__(self):
        self.cursor_obj = FakeCursor()

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False

    def cursor(self):
        return self.cursor_obj


class StagingInspectorTests(unittest.TestCase):
    def test_rejects_invalid_inputs_without_connecting(self):
        self.assertEqual(inspect_postgres_staging(""), (False, "missing", []))
        self.assertEqual(
            inspect_postgres_staging("https://example.com"),
            (False, "invalid_url", []),
        )
        self.assertEqual(
            inspect_postgres_staging("postgresql://example.com/db", "public"),
            (False, "invalid_schema", []),
        )

    def test_only_read_only_metadata_query(self):
        conn = FakeConnection()
        captured = []
        def connect(url, **kwargs):
            captured.append((url, kwargs))
            return conn
        fake_psycopg = types.SimpleNamespace(connect=connect)
        with patch.dict(sys.modules, {"psycopg": fake_psycopg}):
            ok, reason, tables = inspect_postgres_staging(
                "postgresql://user:secret@example.com:5432/db"
            )
        self.assertEqual((ok, reason), (True, "ok"))
        self.assertEqual(tables, ["customers", "migration_check"])
        self.assertEqual(conn.cursor_obj.calls[0][0], "SET TRANSACTION READ ONLY")
        self.assertIn("information_schema.tables", conn.cursor_obj.calls[1][0])
        self.assertEqual(conn.cursor_obj.calls[1][1], ("ct_staging",))
        self.assertEqual(len(conn.cursor_obj.calls), 2)
        self.assertEqual(captured[0][1]["sslmode"], "require")

    def test_connection_errors_are_sanitized(self):
        def fail(*_args, **_kwargs):
            raise RuntimeError("postgresql://user:secret@example.com/db")
        with patch.dict(sys.modules, {"psycopg": types.SimpleNamespace(connect=fail)}):
            self.assertEqual(
                inspect_postgres_staging("postgresql://user:secret@example.com/db"),
                (False, "connection_failed", []),
            )


if __name__ == "__main__":
    unittest.main()
