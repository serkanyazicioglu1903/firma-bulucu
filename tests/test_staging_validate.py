"""Offline tests for read-only Supabase staging structural validation."""
import sys
import types
import unittest
from unittest.mock import patch

from scripts.staging_validate import (
    compare_structure,
    expected_structure,
    validate_staging_structure,
)


class StagingValidationTests(unittest.TestCase):
    def test_schema_matches_exact_expected_metadata(self):
        expected = expected_structure()
        self.assertGreaterEqual(len(expected), 26)
        actual_columns = {
            name: dict(spec["columns"]) for name, spec in expected.items()
        }
        actual_constraints = {
            name: list(spec["constraints"]) for name, spec in expected.items()
        }
        # Existing one-row connectivity check is allowed to remain.
        actual_columns["migration_check"] = {"id": ("text", "YES", "NO")}
        self.assertEqual(
            compare_structure(expected, actual_columns, actual_constraints), []
        )

        actual_columns["customers"]["id"] = ("text", "YES", "NO")
        problems = compare_structure(expected, actual_columns, actual_constraints)
        self.assertTrue(any("customers.id" in item for item in problems))

    def test_constraint_mismatches_are_detected(self):
        expected = expected_structure()
        cols = {name: dict(spec["columns"]) for name, spec in expected.items()}
        constraints = {
            name: list(spec["constraints"]) for name, spec in expected.items()
        }
        target = next(
            name for name, spec in expected.items()
            if any(c[0] == "f" for c in spec["constraints"])
        )
        constraints[target] = [
            c for c in constraints[target] if c[0] != "f"
        ]
        self.assertTrue(
            any(target + ":" in text and "f kısıtı" in text
                for text in compare_structure(expected, cols, constraints))
        )

    def test_connection_validation_and_secret_sanitization(self):
        self.assertEqual(validate_staging_structure(""), ("missing", []))
        self.assertEqual(
            validate_staging_structure("https://example.com"), ("invalid_url", [])
        )
        def fail(*_args, **_kwargs):
            raise ValueError("secret-db-password")
        with patch.dict(
            sys.modules,
            {"psycopg": types.SimpleNamespace(connect=fail)},
        ):
            self.assertEqual(
                validate_staging_structure(
                    "postgresql://user:secret-db-password@example.com/db"
                ),
                ("failed", []),
            )

    def test_auditor_uses_read_only_transaction_and_metadata_only(self):
        expected = expected_structure()

        class Cursor:
            def __init__(self):
                self.statements = []
                self.last = ""

            def __enter__(self):
                return self

            def __exit__(self, *_):
                return False

            def execute(self, sql, params=None):
                self.statements.append((sql, params))
                self.last = sql

            def fetchall(self):
                if "information_schema.columns" in self.last:
                    return [
                        (table, col, kind, nullable, identity)
                        for table, spec in expected.items()
                        for col, (kind, nullable, identity) in spec["columns"].items()
                    ]
                if "pg_catalog.pg_constraint" in self.last:
                    return [
                        (table, kind, list(cols), referenced, list(refcols))
                        for table, spec in expected.items()
                        for kind, cols, referenced, refcols in spec["constraints"]
                    ]
                return []

        class Connection:
            def __init__(self):
                self.cursor_instance = Cursor()

            def __enter__(self):
                return self

            def __exit__(self, *_):
                return False

            def cursor(self):
                return self.cursor_instance

        conn = Connection()
        with patch.dict(
            sys.modules,
            {"psycopg": types.SimpleNamespace(connect=lambda *_a, **_k: conn)},
        ):
            self.assertEqual(
                validate_staging_structure("postgresql://u:p@localhost/db"),
                ("ok", []),
            )
        queries = conn.cursor_instance.statements
        self.assertEqual(queries[0][0], "SET TRANSACTION READ ONLY")
        self.assertEqual(queries[1][1], ("ct_staging",))
        self.assertEqual(queries[2][1], ("ct_staging",))
        self.assertEqual(len(queries), 3)
        self.assertFalse(
            any(
                "SELECT *" in sql or "INSERT " in sql or "UPDATE " in sql
                or "DELETE " in sql or "CREATE " in sql
                for sql, _ in queries
            )
        )


if __name__ == "__main__":
    unittest.main()
