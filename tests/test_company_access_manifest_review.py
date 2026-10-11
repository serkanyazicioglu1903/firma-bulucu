"""Offline four-company permission planning never writes rights or real data."""
import copy
import unittest

from scripts import company_access_manifest_review as m

USERS = [
    {"username": "admin_a", "role": "ADMIN", "enabled": True,
     "password_hash": "synthetic-not-in-fingerprint"},
    {"username": "finance_b", "role": "FINANCE", "enabled": True},
    {"username": "viewer_c", "role": "VIEWER", "enabled": True},
    {"username": "disabled_d", "role": "ADMIN", "enabled": False},
]


def grant(code="AS_ILERI_GIDA", write=False):
    return {
        "company_code": code, "can_read": True,
        "can_write": write, "evidence_ref": "FILE-000123",
    }


def plan(users=USERS):
    return {
        "source_sha256": m.registry_fingerprint(users),
        "decisions": [
            {
                "username": user["username"], "role": user["role"],
                "enabled": user["enabled"], "decision_ref": "REVIEW-20261011",
                "grants": (
                    [grant()] if user["username"] == "admin_a" else
                    [grant("PLANET_INGREDIENTS", write=True)]
                    if user["username"] == "finance_b" else []
                ),
            }
            for user in users
        ],
    }


class PermissionPlanTests(unittest.TestCase):
    def test_exact_roles_and_explicit_company_grants_need_human_review(self):
        result = m.review_permission_manifest(USERS, plan())
        self.assertEqual(result["status"], "review_required")
        self.assertEqual(result["reviewed_accounts"], 4)
        self.assertEqual(result["enabled_accounts"], 3)
        self.assertEqual(result["proposed_company_reads"], 2)
        self.assertEqual(result["proposed_company_writes"], 1)
        self.assertFalse(result["real_permissions_granted"])
        self.assertFalse(result["production_authorized"])

    def test_password_fields_not_part_of_review_fingerprint(self):
        with_password_change = copy.deepcopy(USERS)
        with_password_change[0]["password_hash"] = "synthetic-rotated"
        self.assertEqual(m.registry_fingerprint(USERS),
                         m.registry_fingerprint(with_password_change))
        self.assertNotIn("synthetic", str(m.review_permission_manifest(USERS, plan())))

    def test_registry_role_and_enablement_changes_are_stale(self):
        for change in (("role", "PURCHASING"), ("enabled", False)):
            users = copy.deepcopy(USERS)
            users[1][change[0]] = change[1]
            result = m.review_permission_manifest(users, plan())
            self.assertEqual(result["issue_codes"], ("stale_or_invalid_source",))

    def test_duplicate_account_and_incorrect_registry_rejected(self):
        self.assertEqual(
            m.review_permission_manifest(USERS + [USERS[0]], plan())["issue_codes"],
            ("invalid_registry",),
        )
        bad = copy.deepcopy(USERS)
        bad[0]["enabled"] = "true"
        self.assertEqual(
            m.review_permission_manifest(bad, plan())["issue_codes"],
            ("invalid_registry",),
        )

    def test_every_user_requires_explicit_decision_even_disabled(self):
        item = plan()
        item["decisions"].pop()
        self.assertEqual(m.review_permission_manifest(USERS, item)["issue_codes"],
                         ("incomplete_decisions",))
        item = plan()
        item["decisions"][3]["grants"] = [grant("AS_FOOD_GLOBAL")]
        self.assertEqual(m.review_permission_manifest(USERS, item)["issue_codes"],
                         ("disabled_user_granted",))

    def test_wrong_or_duplicate_company_cannot_be_granted(self):
        for code in ("*", "UNKNOWN", "as_ileri_gida", ""):
            item = plan()
            item["decisions"][0]["grants"] = [grant(code)]
            self.assertEqual(m.review_permission_manifest(USERS, item)["status"],
                             "blocked")
        item = plan()
        item["decisions"][0]["grants"] = [grant(), grant()]
        self.assertEqual(m.review_permission_manifest(USERS, item)["issue_codes"],
                         ("invalid_grants",))

    def test_read_must_be_explicit_and_write_implies_read(self):
        for bad in (
            {"can_read": False, "can_write": True},
            {"can_read": "true", "can_write": False},
            {"can_read": True, "can_write": 1},
        ):
            item = plan()
            item["decisions"][0]["grants"][0].update(bad)
            self.assertEqual(m.review_permission_manifest(USERS, item)["status"],
                             "blocked")

    def test_role_without_scoped_write_rehearsal_is_denied_write(self):
        for name in ("viewer_c",):
            item = plan()
            for decision in item["decisions"]:
                if decision["username"] == name:
                    decision["grants"] = [grant(write=True)]
            self.assertEqual(m.review_permission_manifest(USERS, item)["issue_codes"],
                             ("role_write_not_rehearsed",))
        sales = [{"username": "sales", "role": "SALES", "enabled": True}]
        item = plan(sales)
        item["decisions"][0]["grants"] = [grant(write=True)]
        self.assertEqual(m.review_permission_manifest(sales, item)["issue_codes"],
                         ("role_write_not_rehearsed",))

    def test_evidence_refs_required_for_user_and_each_grant(self):
        item = plan()
        item["decisions"][0]["decision_ref"] = ""
        self.assertEqual(m.review_permission_manifest(USERS, item)["issue_codes"],
                         ("invalid_decision",))
        item = plan()
        item["decisions"][0]["grants"][0]["evidence_ref"] = ""
        self.assertEqual(m.review_permission_manifest(USERS, item)["issue_codes"],
                         ("invalid_grants",))

    def test_duplicate_manifest_user_and_unexpected_fields_denied(self):
        item = plan()
        item["decisions"][1] = copy.deepcopy(item["decisions"][0])
        self.assertEqual(m.review_permission_manifest(USERS, item)["issue_codes"],
                         ("invalid_decision",))
        item = plan()
        item["decisions"][0]["grants"][0]["secret_password"] = "not allowed"
        self.assertEqual(m.review_permission_manifest(USERS, item)["issue_codes"],
                         ("invalid_grants",))

    def test_no_grants_is_not_auto_approval(self):
        item = plan()
        for decision in item["decisions"]:
            decision["grants"] = []
        result = m.review_permission_manifest(USERS, item)
        self.assertEqual(result["status"], "review_required")
        self.assertEqual(result["proposed_company_reads"], 0)
        self.assertFalse(result["production_authorized"])


if __name__ == "__main__":
    unittest.main()
