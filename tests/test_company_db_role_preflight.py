"""Offline tests for the real-user/least-privilege readiness contracts."""
from copy import deepcopy
from pathlib import Path
import unittest
from unittest.mock import MagicMock

from scripts.company_db_role_preflight import (
    review_postgres_app_role_on_cursor,
)
from scripts.company_user_db_role_manifest import (
    review_app_to_database_roles,
)
from scripts.company_access_manifest_review import registry_fingerprint
from scripts.four_company_foundation_ddl import private_company_tables

APP_ROLE = "ct_sales_001"
USERS = [
    {"username": "account_one", "role": "SALES", "enabled": True},
    {"username": "account_two", "role": "FINANCE", "enabled": True},
    {"username": "retired", "role": "ADMIN", "enabled": False},
]


def good_cursor(*, session=APP_ROLE, superuser=False, bypass=False,
                createrole=False, createdb=False, login=True,
                schema_usage=True, memberships=0, rows=None):
    cursor = MagicMock()
    cursor.fetchone.side_effect = [
        (APP_ROLE, session, superuser, bypass, createrole, createdb,
         login, schema_usage),
        (memberships,),
    ]
    if rows is None:
        rows = [
            (table, True, True, False, table == "customers",
             False, 1, 1)
            for table in private_company_tables()
        ]
    cursor.fetchall.return_value = rows
    return cursor


def sample_plan():
    return {
        "source_sha256": registry_fingerprint(USERS),
        "bindings": [
            {"username": "account_one", "db_role": "ct_sales_001",
             "evidence_ref": "SECURITY-REVIEW-1001"},
            {"username": "account_two", "db_role": "ct_finance_002",
             "evidence_ref": "SECURITY-REVIEW-1002"},
            {"username": "retired", "db_role": None,
             "evidence_ref": "SECURITY-REVIEW-1003"},
        ],
    }


class CompanyDbRolePreflightTests(unittest.TestCase):
    def test_valid_catalog_is_only_review_not_production_authority(self):
        cur = good_cursor()
        report = review_postgres_app_role_on_cursor(cur, APP_ROLE)
        self.assertEqual(report["status"], "review_required")
        self.assertEqual(report["tables_checked"], 23)
        self.assertEqual(report["selectable_company_tables"], 1)
        self.assertTrue(report["least_privilege_review"])
        self.assertFalse(report["user_identity_bound"])
        self.assertFalse(report["company_entitlements_applied"])
        self.assertFalse(report["production_authorized"])
        self.assertEqual(cur.execute.call_count, 3)
        self.assertTrue(all(
            call.args[0].startswith("SELECT ")
            for call in cur.execute.call_args_list
        ))

    def test_invalid_or_elevated_roles_denied(self):
        for role in ("postgres", "service_role", "anon", "authenticated",
                     "x", "*", "ct_manager;DROP TABLE", "SUPABASE"):
            cur = MagicMock()
            with self.subTest(role=role):
                result = review_postgres_app_role_on_cursor(cur, role)
                self.assertEqual(result["status"], "blocked")
                cur.execute.assert_not_called()
        for overrides, issue in (
            ({"session": "postgres"}, "not_direct_authenticated_db_role"),
            ({"superuser": True}, "elevated_db_role"),
            ({"bypass": True}, "elevated_db_role"),
            ({"createrole": True}, "elevated_db_role"),
            ({"createdb": True}, "elevated_db_role"),
            ({"login": False}, "not_direct_authenticated_db_role"),
            ({"schema_usage": False}, "no_schema_usage"),
            ({"memberships": 1}, "unreviewed_role_memberships"),
        ):
            with self.subTest(overrides=overrides):
                cur = good_cursor(**overrides)
                self.assertEqual(
                    review_postgres_app_role_on_cursor(cur, APP_ROLE)
                    ["issue_codes"], (issue,),
                )

    def test_rls_owner_or_policy_gap_denied(self):
        baseline = good_cursor().fetchall()
        self.assertEqual(len(baseline), 23)
        for idx, new_value, issue in (
            (1, False, "company_rls_missing"),
            (2, False, "company_rls_missing"),
            (3, True, "company_table_owner_role"),
            (6, 0, "company_rls_missing"),
            (7, 0, "company_rls_missing"),
        ):
            rows = list(baseline)
            item = list(rows[0])
            item[idx] = new_value
            rows[0] = tuple(item)
            with self.subTest(index=idx):
                cur = good_cursor(rows=rows)
                self.assertEqual(
                    review_postgres_app_role_on_cursor(cur, APP_ROLE)
                    ["issue_codes"], (issue,),
                )
        only_no_reads = [
            (name, True, True, False, False, False, 1, 1)
            for name in private_company_tables()
        ]
        self.assertEqual(
            review_postgres_app_role_on_cursor(
                good_cursor(rows=only_no_reads), APP_ROLE
            )["issue_codes"], ("no_business_table_privileges",),
        )
        self.assertEqual(
            review_postgres_app_role_on_cursor(
                good_cursor(rows=baseline[:-1]), APP_ROLE
            )["issue_codes"], ("owner_table_inventory_incomplete",),
        )

    def test_failclosed_on_metadata_exception(self):
        cur = MagicMock()
        cur.execute.side_effect = ValueError("Never echo a secret")
        result = review_postgres_app_role_on_cursor(cur, APP_ROLE)
        self.assertEqual(result["issue_codes"], ("metadata_unavailable",))
        self.assertNotIn("Never echo", str(result))


class AppToDbRoleManifestTests(unittest.TestCase):
    def test_exact_manual_bindings_still_cannot_grant_live_rights(self):
        summary = review_app_to_database_roles(USERS, sample_plan())
        self.assertEqual(summary["status"], "review_required")
        self.assertEqual(summary["reviewed_users"], 3)
        self.assertEqual(summary["proposed_role_bindings"], 2)
        self.assertFalse(summary["database_login_verified"])
        self.assertFalse(summary["company_permissions_granted"])
        self.assertFalse(summary["production_authorized"])
        self.assertNotIn("account_one", str(summary))

    def test_invalid_plan_and_account_state_changes_denied(self):
        for mutate in (
            lambda p: p["bindings"].pop(),
            lambda p: p["bindings"][0].update(db_role="postgres"),
            lambda p: p["bindings"][0].update(db_role="service_role"),
            lambda p: p["bindings"][0].update(db_role="ct_finance_002"),
            lambda p: p["bindings"][0].update(db_role="*"),
            lambda p: p["bindings"][2].update(db_role=APP_ROLE),
            lambda p: p["bindings"][0].update(evidence_ref=""),
            lambda p: p["bindings"][1].update(username="account_one"),
        ):
            p = sample_plan()
            mutate(p)
            self.assertEqual(
                review_app_to_database_roles(USERS, p)["status"], "blocked"
            )
        changed = deepcopy(USERS)
        changed[0]["role"] = "ADMIN"
        self.assertEqual(
            review_app_to_database_roles(changed, sample_plan())
            ["issue_codes"], ("stale_or_incomplete_account_plan",),
        )
        changed = deepcopy(USERS)
        changed[0]["enabled"] = False
        self.assertEqual(
            review_app_to_database_roles(changed, sample_plan())
            ["issue_codes"], ("stale_or_incomplete_account_plan",),
        )

    def test_source_modules_have_no_grant_or_live_connection(self):
        folder = Path(__file__).resolve().parents[1] / "scripts"
        for name in (
            "company_db_role_preflight.py",
            "company_user_db_role_manifest.py",
        ):
            src = (folder / name).read_text()
            for forbidden in (
                "INSERT INTO", "ALTER ROLE", "CREATE ROLE",
                "psycopg.connect", "import streamlit",
                "load_users(", "os.environ",
            ):
                self.assertNotIn(forbidden, src, (name, forbidden))


if __name__ == "__main__":
    unittest.main()
