"""Offline regression tests for rollback-only PostgreSQL staging transaction smoke."""
import sys
import types
import unittest
from unittest.mock import patch

from scripts.staging_transaction_smoke import (
    VERIFIED_TABLES,
    run_transactional_staging_smoke,
    validate_test_url,
)


class FakeTransaction:
    def __init__(self, connection):
        self.connection = connection

    def __enter__(self):
        self.connection.in_tx = True
        return self

    def __exit__(self, exc_type, _exc, _tb):
        self.connection.in_tx = False
        self.connection.rolled_back = exc_type is not None
        return False


class FakeCursor:
    def __init__(self, connection):
        self.connection = connection
        self.last_sql = ""

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False

    def execute(self, sql, params=None):
        self.last_sql = sql
        self.connection.sql.append((sql, params, self.connection.in_tx))
        if sql.startswith(("INSERT ", "UPDATE ", "DELETE ")):
            if not self.connection.in_tx:
                raise AssertionError("DML outside rollback transaction")
            if self.connection.simulate_write_failure:
                raise RuntimeError("simulated DB write failure")
        if sql.startswith('INSERT INTO "ct_staging"."customers"'):
            self.connection.marker = params[1].removesuffix("_CUSTOMER")
        if sql.startswith('DELETE FROM "ct_staging"."tasks"'):
            self.connection.deleted_task = True

    def fetchone(self):
        sql = self.last_sql
        if sql.startswith("SELECT q.quantity_kg"):
            return (100.0, self.connection.marker + "_CUSTOMER",
                    self.connection.marker + "_PRODUCT")
        if sql.startswith("SELECT status FROM"):
            return ("Tamamlandı",)
        if sql.startswith("SELECT id FROM"):
            return None if self.connection.deleted_task else (123,)
        if sql.startswith("SELECT l.quantity_available_kg"):
            return (75.0, 100.0)
        if sql.startswith("SELECT r.amount"):
            return (450.0, 320.0)
        if sql.startswith('SELECT 1 FROM "ct_staging"'):
            if not self.connection.rolled_back:
                raise AssertionError("Checked data before rollback")
            return None
        raise AssertionError("Unexpected SELECT query")


class FakeConnection:
    def __init__(self):
        self.sql = []
        self.in_tx = False
        self.rolled_back = False
        self.deleted_task = False
        self.marker = None
        self.simulate_write_failure = False

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False

    def transaction(self):
        return FakeTransaction(self)

    def cursor(self):
        return FakeCursor(self)


class PostgresSmokeTests(unittest.TestCase):
    def test_rejects_missing_and_non_postgres_urls(self):
        self.assertFalse(validate_test_url(""))
        self.assertFalse(validate_test_url("https://example.org"))
        self.assertTrue(validate_test_url("postgresql://u:pw@localhost/db"))
        self.assertEqual(run_transactional_staging_smoke(""), ("invalid_url", []))

    def test_fails_closed_if_schema_not_verified(self):
        with patch(
            "scripts.staging_transaction_smoke.validate_staging_structure",
            return_value=("mismatch", ["missing PK"]),
        ):
            self.assertEqual(
                run_transactional_staging_smoke("postgresql://u:pw@localhost/db"),
                ("schema_mismatch", []),
            )

    def test_all_test_writes_rollback_and_identifiers_are_fixed(self):
        conn = FakeConnection()
        captured = []
        def connect(url, **kwargs):
            captured.append(kwargs)
            return conn
        with patch(
            "scripts.staging_transaction_smoke.validate_staging_structure",
            return_value=("ok", []),
        ), patch.dict(
            sys.modules,
            {"psycopg": types.SimpleNamespace(connect=connect)},
        ):
            result = run_transactional_staging_smoke(
                "postgresql://user:hidden-password@example.org/db"
            )

        self.assertEqual(result[0], "passed")
        self.assertIn("Finans", result[1])
        self.assertTrue(conn.rolled_back)
        self.assertEqual(captured[0]["sslmode"], "require")
        self.assertTrue(captured[0]["autocommit"])
        statements = [sql for sql, _, _ in conn.sql]
        self.assertEqual(
            sum(s.startswith('SELECT 1 FROM "ct_staging"') for s in statements),
            len(VERIFIED_TABLES),
        )
        self.assertTrue(any(s.startswith("INSERT INTO ") for s in statements))
        self.assertTrue(any(s.startswith("UPDATE ") for s in statements))
        self.assertTrue(any(s.startswith("DELETE ") for s in statements))
        self.assertFalse(any(
            s.startswith(("DROP ", "TRUNCATE ", "CREATE ", "ALTER "))
            for s in statements
        ))
        self.assertFalse(any("public." in s for s in statements))
        for sql, params, _ in conn.sql:
            if sql.startswith("INSERT INTO"):
                self.assertEqual(params[0] < 0, True)

    def test_failed_write_rolls_back_without_reporting_success(self):
        conn = FakeConnection()
        conn.simulate_write_failure = True
        with patch(
            "scripts.staging_transaction_smoke.validate_staging_structure",
            return_value=("ok", []),
        ), patch.dict(
            sys.modules,
            {"psycopg": types.SimpleNamespace(connect=lambda *_a, **_k: conn)},
        ):
            result = run_transactional_staging_smoke(
                "postgresql://user:hidden-password@example.org/db"
            )
        self.assertEqual(result, ("failed", []))
        self.assertTrue(conn.rolled_back)
        self.assertFalse(conn.in_tx)

    def test_exception_is_sanitized(self):
        def fail(*_args, **_kwargs):
            raise ValueError("embedded private database credentials")
        with patch(
            "scripts.staging_transaction_smoke.validate_staging_structure",
            return_value=("ok", []),
        ), patch.dict(
            sys.modules,
            {"psycopg": types.SimpleNamespace(connect=fail)},
        ):
            self.assertEqual(
                run_transactional_staging_smoke(
                    "postgresql://user:secret@example.org/db"
                ),
                ("failed", []),
            )


if __name__ == "__main__":
    unittest.main()
