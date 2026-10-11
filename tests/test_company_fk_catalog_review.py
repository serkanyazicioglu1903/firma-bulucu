"""Offline structural FK checks before four-company row migration."""
import copy
from pathlib import Path
import unittest
from unittest.mock import MagicMock, patch

from scripts.company_fk_catalog_review import (
    evaluate_blueprint_fks, inspect_blueprint_fks,
    inspect_blueprint_fks_on_cursor,
)
from scripts.group_company_catalog import COMPANY_LABELS
from scripts.postgres_company_full_coverage import REVIEW_GROUPS, _catalog_tables


def fictional_blueprint(*, child="contacts", field="customer_id",
                         parent="customers"):
    """Fictional legal names; no user IDs, no production records or grants."""
    companies = [
        {"code": code, "legal_name": f"Fictional Corporation {number}",
         "evidence_ref": f"REVIEW-FAKE-{number}"}
        for number, code in enumerate(COMPANY_LABELS, 1)
    ]
    tables = []
    for group, members in REVIEW_GROUPS.items():
        for table in members:
            strategy = ("shared_candidate" if group == "shared_master_decision"
                        else "internal_only" if group == "internal_access_decision"
                        else "direct_owner")
            tables.append({
                "table": table,
                "mode": strategy,
                "parent_table": None,
                "fk_column": None,
                "evidence_ref": "REVIEW-ARCH-0001",
            })
    if child:
        proposed = next(entry for entry in tables if entry["table"] == child)
        proposed.update(
            mode="parent_scoped", parent_table=parent, fk_column=field
        )
    return {"companies": companies, "tables": tables}


PHYSICAL = tuple(sorted(_catalog_tables()))
PRESENT = [
    ("contacts", "customer_id", "customers", "id", True, True),
    ("activities", "customer_id", "customers", "id", True, True),
]


class CompanyFkCatalogReviewTests(unittest.TestCase):
    def test_verified_fk_still_does_not_approve_real_company_isolation(self):
        report = evaluate_blueprint_fks(fictional_blueprint(), PHYSICAL, PRESENT)
        self.assertEqual(report["status"], "review_required")
        self.assertEqual(report["checked_tables"], 26)
        self.assertEqual(report["proposed_parent_paths"], 1)
        self.assertEqual(report["validated_parent_paths"], 1)
        for key in (
            "legal_ownership_verified", "database_company_isolation_verified",
            "real_user_permissions_verified", "production_approved",
        ):
            self.assertFalse(report[key])

    def test_unchecked_or_fake_foreign_key_denied(self):
        for change, expected in (
            ({"field": "account_id"}, "missing_physical_fk"),
            ({"parent": "warehouses"}, "missing_physical_fk"),
        ):
            with self.subTest(change=change):
                report = evaluate_blueprint_fks(
                    fictional_blueprint(**change), PHYSICAL, PRESENT
                )
                self.assertEqual(report["issue_codes"], (expected,))

    def test_nullable_or_unvalidated_constraint_denied(self):
        for attr, issue in ((4, "nullable_parent_fk"), (5, "unvalidated_fk")):
            row = list(PRESENT[0])
            row[attr] = False
            report = evaluate_blueprint_fks(
                fictional_blueprint(), PHYSICAL, [tuple(row)]
            )
            self.assertEqual(report["issue_codes"], (issue,))

    def test_corrupted_catalog_or_schema_rejected(self):
        invalid = (
            PHYSICAL[:-1],
            PHYSICAL + ("customers",),
            PHYSICAL[:-1] + ("unknown",),
            None,
        )
        for tables in invalid:
            with self.subTest(tables=str(tables)[-30:]):
                self.assertEqual(
                    evaluate_blueprint_fks(
                        fictional_blueprint(), tables, PRESENT
                    )["issue_codes"],
                    ("schema_mismatch",),
                )
        for fks in (
            [PRESENT[0], PRESENT[0]],
            [("contacts", "customer_id", "customers", "id", 1, True)],
            [("contacts", "customer_id", "customers")],
            [("other", "customer_id", "customers", "id", True, True)],
        ):
            with self.subTest(fks=fks):
                self.assertEqual(
                    evaluate_blueprint_fks(
                        fictional_blueprint(), PHYSICAL, fks
                    )["status"],
                    "blocked",
                )

    def test_plan_shape_must_pass_existing_four_company_26_table_gate(self):
        blueprint = fictional_blueprint()
        blueprint["companies"].pop()
        self.assertEqual(
            evaluate_blueprint_fks(blueprint, PHYSICAL, PRESENT)["issue_codes"],
            ("invalid_blueprint",),
        )
        blueprint = fictional_blueprint()
        blueprint["tables"].pop()
        self.assertEqual(
            evaluate_blueprint_fks(blueprint, PHYSICAL, PRESENT)["issue_codes"],
            ("invalid_blueprint",),
        )

    def test_catalog_queries_are_select_only_no_sensitive_business_rows(self):
        cursor = MagicMock()
        cursor.fetchall.side_effect = [
            [(table,) for table in PHYSICAL], PRESENT,
        ]
        result = inspect_blueprint_fks_on_cursor(
            cursor, fictional_blueprint()
        )
        self.assertEqual(result["status"], "review_required")
        self.assertEqual(cursor.execute.call_count, 2)
        for call in cursor.execute.call_args_list:
            sql = call.args[0]
            self.assertTrue(sql.startswith("SELECT "))
            self.assertIn("pg_", sql)
            self.assertNotIn("FROM ct_app.", sql)
            self.assertNotIn("INSERT", sql)
            self.assertNotIn("UPDATE", sql)

    @patch("psycopg.connect")
    def test_invalid_url_does_not_connect(self, connection):
        result = inspect_blueprint_fks(
            "sqlite:///invalid-source",
            fictional_blueprint(),
        )
        self.assertEqual(result["status"], "blocked")
        connection.assert_not_called()

    def test_check_module_does_not_import_env_or_provision_schema(self):
        source = (Path(__file__).resolve().parents[1]
                  / "scripts" / "company_fk_catalog_review.py").read_text()
        self.assertNotIn("os.environ", source)
        self.assertNotIn("CREATE TABLE", source)
        self.assertNotIn("ALTER TABLE", source)
        self.assertNotIn("DELETE FROM", source)
        self.assertNotIn("INSERT INTO", source)


if __name__ == "__main__":
    unittest.main()
