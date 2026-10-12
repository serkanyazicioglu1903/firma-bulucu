"""Synthetic sole-owner four-company pilot: no real account or DB changes."""
from copy import deepcopy
from pathlib import Path
import unittest

from scripts.company_access_manifest_review import registry_fingerprint
from scripts.group_company_catalog import COMPANY_LABELS
from scripts.sole_owner_four_company_pilot import review_sole_owner_pilot


ACCOUNTS = [
    {"username": "pilot_admin", "role": "ADMIN", "enabled": True,
     "password_hash": "synthetic-ignored"},
    {"username": "other_admin", "role": "ADMIN", "enabled": False},
    {"username": "other_finance", "role": "FINANCE", "enabled": False},
]
OWNER = "pilot_admin"
EVIDENCE = "OWNER-REVIEW-20261012"


def manifest(accounts=ACCOUNTS):
    return {
        "source_sha256": registry_fingerprint(accounts),
        "decisions": [
            {
                "username": user["username"],
                "role": user["role"],
                "enabled": user["enabled"],
                "decision_ref": EVIDENCE,
                "grants": [
                    {"company_code": code, "can_read": True,
                     "can_write": False, "evidence_ref": EVIDENCE}
                    for code in COMPANY_LABELS
                ] if user["username"] == OWNER else [],
            }
            for user in accounts
        ],
    }


def role_manifest(accounts=ACCOUNTS):
    return {
        "source_sha256": registry_fingerprint(accounts),
        "bindings": [
            {
                "username": user["username"],
                "db_role": "ct_pilot_admin" if user["username"] == OWNER
                           else None,
                "evidence_ref": EVIDENCE,
            }
            for user in accounts
        ],
    }


def review(accounts=ACCOUNTS, rights=None, roles=None,
           username=OWNER, approval=EVIDENCE):
    return review_sole_owner_pilot(
        accounts, rights if rights is not None else manifest(accounts),
        roles if roles is not None else role_manifest(accounts),
        username, approval,
    )


class SoleOwnerPilotTests(unittest.TestCase):
    def test_sole_owner_exact_four_reads_and_zero_writes(self):
        report = review()
        self.assertEqual(report["status"], "review_required")
        self.assertEqual(report["accounts_reviewed"], 3)
        self.assertEqual(report["enabled_accounts"], 1)
        self.assertEqual(report["company_read_scopes"], 4)
        self.assertEqual(report["company_write_scopes"], 0)
        self.assertEqual(report["proposed_database_roles"], 1)
        self.assertFalse(report["other_accounts_enabled"])
        for key in ("actual_credentials_verified",
                    "actual_company_grants_created",
                    "actual_db_roles_created",
                    "live_company_isolation_verified",
                    "production_authorized"):
            self.assertFalse(report[key])
        self.assertNotIn(OWNER, str(report))
        self.assertNotIn("password_hash", str(report))

    def test_other_enabled_account_even_admin_denied(self):
        for account_index in (1, 2):
            accounts = deepcopy(ACCOUNTS)
            accounts[account_index]["enabled"] = True
            self.assertEqual(review(accounts)["issue_codes"],
                             ("not_exclusive_active_admin",))
        accounts = deepcopy(ACCOUNTS)
        accounts[0]["enabled"] = False
        self.assertEqual(review(accounts)["status"], "blocked")

    def test_user_role_cannot_auto_confer_company_privileges(self):
        accounts = deepcopy(ACCOUNTS)
        accounts[0]["role"] = "VIEWER"
        self.assertEqual(review(accounts)["issue_codes"],
                         ("not_exclusive_active_admin",))
        self.assertEqual(review(username="other_admin")["issue_codes"],
                         ("not_exclusive_active_admin",))
        self.assertEqual(review(username="missing")["issue_codes"],
                         ("owner_identity_not_reviewed",))
        self.assertEqual(review(approval="")["issue_codes"],
                         ("owner_identity_not_reviewed",))

    def test_exactly_four_explicit_read_scopes_and_no_write(self):
        for mutation in (
            lambda p: p["decisions"][0]["grants"].pop(),
            lambda p: p["decisions"][0]["grants"][0].update(can_write=True),
            lambda p: p["decisions"][0]["grants"][0].update(can_read=False),
            lambda p: p["decisions"][0]["grants"][0].update(company_code="*"),
            lambda p: p["decisions"][0]["grants"][1].update(
                company_code="AS_ILERI_GIDA"),
            lambda p: p["decisions"][1].update(grants=[
                {"company_code": "AS_ILERI_GIDA", "can_read": True,
                 "can_write": False, "evidence_ref": EVIDENCE}]),
        ):
            plan = manifest()
            mutation(plan)
            self.assertEqual(review(rights=plan)["status"], "blocked")

    def test_extra_proposed_db_role_and_stale_registry_denied(self):
        for mutation in (
            lambda p: p["bindings"][0].update(db_role="postgres"),
            lambda p: p["bindings"][1].update(db_role="ct_other_admin"),
            lambda p: p["bindings"][0].update(db_role=None),
            lambda p: p["bindings"][0].update(db_role="service_role"),
            lambda p: p["bindings"].pop(),
            lambda p: p.update(source_sha256="0"*64),
        ):
            plan = role_manifest()
            mutation(plan)
            self.assertEqual(review(roles=plan)["status"], "blocked")
        changed = deepcopy(ACCOUNTS)
        changed[0]["role"] = "SALES"
        self.assertEqual(
            review_sole_owner_pilot(changed, manifest(), role_manifest(),
                                    OWNER, EVIDENCE)["status"],
            "blocked",
        )

    def test_no_production_runner_or_credentials(self):
        content = (Path(__file__).resolve().parents[1] / "scripts" /
                   "sole_owner_four_company_pilot.py").read_text()
        for forbidden in ("psycopg.connect", "INSERT INTO",
                          "UPDATE ct_app", "CREATE ROLE", "ALTER ROLE",
                          "import streamlit", "APP_USERS_JSON",
                          "st.session_state", "os.environ"):
            self.assertNotIn(forbidden, content)


if __name__ == "__main__":
    unittest.main()
