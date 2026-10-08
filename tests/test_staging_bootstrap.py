"""Offline safety tests for staging schema creation; never connects to Supabase."""
import re
import sys
import types
import unittest
from unittest.mock import patch

from scripts.staging_bootstrap import bootstrap_staging, classify_existing_tables


class FakeCursor:
    def __init__(self, existing):
        self.existing = set(existing)
        self.sql = []
        self.last = None

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False

    def execute(self, statement, params=None):
        self.sql.append((statement, params))
        if "pg_catalog.pg_namespace WHERE" in statement:
            self.last = "namespace"
        elif "pg_catalog.pg_class AS c" in statement:
            self.last = "tables"
        elif statement.startswith("CREATE TABLE "):
            name = re.search(r'^CREATE TABLE "([a-z_]+)"', statement).group(1)
            self.existing.add(name)
            self.last = None
        else:
            self.last = None

    def fetchone(self):
        return (1,) if self.last == "namespace" else None

    def fetchall(self):
        return [(table,) for table in sorted(self.existing)] if self.last == "tables" else []


class FakeConn:
    def __init__(self, existing):
        self.cursor_obj = FakeCursor(existing)

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False

    def transaction(self):
        return self

    def cursor(self):
        return self.cursor_obj


class StagingBootstrapTests(unittest.TestCase):
    def test_guard_rejects_partial_and_unknown_tables(self):
        wanted = ["customers", "tasks"]
        self.assertEqual(classify_existing_tables(["migration_check"], wanted), "create")
        self.assertEqual(classify_existing_tables(["customers"], wanted), "conflict")
        self.assertEqual(classify_existing_tables(["unknown"], wanted), "conflict")
        self.assertEqual(classify_existing_tables(wanted, wanted), "already_present")
        self.assertEqual(
            classify_existing_tables(wanted + ["migration_check"], wanted),
            "already_present",
        )

    def test_invalid_connection_is_rejected(self):
        self.assertEqual(bootstrap_staging(""), ("missing", 0))
        self.assertEqual(bootstrap_staging("https://example.com"), ("invalid_url", 0))

    def test_only_staging_ddl_and_no_business_data(self):
        conn = FakeConn(["migration_check"])
        connections = []
        def connect(*args, **kwargs):
            connections.append(kwargs)
            return conn
        with patch.dict(sys.modules, {"psycopg": types.SimpleNamespace(connect=connect)}):
            status, count = bootstrap_staging("postgresql://user:secret@example.com/db")
        self.assertEqual(status, "created")
        self.assertGreaterEqual(count, 26)
        statements = [s for s, _ in conn.cursor_obj.sql]
        self.assertEqual(sum(s.startswith("CREATE TABLE ") for s in statements), count)
        self.assertTrue(any(s.startswith("ALTER TABLE ") for s in statements))
        self.assertIn('SET LOCAL search_path TO "ct_staging", pg_catalog', statements)
        self.assertFalse(any("DROP " in s or "DELETE " in s or "INSERT " in s for s in statements))
        self.assertEqual(connections[0]["sslmode"], "require")
        self.assertTrue(connections[0]["autocommit"])

    def test_existing_app_table_prevents_any_create(self):
        conn = FakeConn(["migration_check", "customers"])
        with patch.dict(
            sys.modules,
            {"psycopg": types.SimpleNamespace(connect=lambda *_a, **_kw: conn)},
        ):
            status, _ = bootstrap_staging("postgresql://example.com/db")
        self.assertEqual(status, "conflict")
        self.assertFalse(
            any(s.startswith("CREATE TABLE ") for s, _ in conn.cursor_obj.sql)
        )


if __name__ == "__main__":
    unittest.main()
