"""Synthetic tests; no real user directory, credentials or Supabase connection."""
import json
import unittest

from scripts.sole_owner_login_readiness import review_owner_login_config as review

HASH = "pbkdf2_sha256$200000$" + "abcdef1234567890" * 2 + "$" + "a" * 64
KEY = "abcdefghijklmnopqrstuvwxyzABCDEF1234567890"


def user(name="serkan", enabled=True, role="ADMIN", password_hash=HASH):
    return {"username": name, "enabled": enabled, "role": role,
            "password_hash": password_hash}


def check(accounts=None, key=KEY, owner="serkan", legacy=False):
    return review(json.dumps(accounts if accounts is not None else [user()]),
                  key, owner, legacy)


class SoleOwnerLoginReadinessTests(unittest.TestCase):
    def test_owner_only_is_review_not_live_approval(self):
        r = check()
        self.assertEqual(r["status"], "review_required")
        self.assertEqual(r["enabled_accounts"], 1)
        self.assertTrue(r["password_hash_format_verified"])
        self.assertTrue(r["signed_session_configured"])
        self.assertFalse(r["credentials_authenticated"])
        self.assertFalse(r["other_accounts_disabled_in_production"])
        self.assertFalse(r["production_authorized"])
        self.assertNotIn("serkan", str(r))
        self.assertNotIn(HASH, str(r))
        self.assertNotIn(KEY, str(r))

    def test_disabled_other_accounts_are_accepted_as_proposals(self):
        r = check([user(), user("finance", False, "FINANCE")])
        self.assertEqual(r["status"], "review_required")
        self.assertEqual(r["accounts_reviewed"], 2)

    def test_other_enabled_account_blocks(self):
        self.assertEqual(check([user(), user("finance", True, "FINANCE")])
                         ["issue_codes"], ("another_account_enabled",))

    def test_other_admin_enabled_blocks(self):
        self.assertEqual(check([user(), user("another", True, "ADMIN")])
                         ["status"], "blocked")

    def test_missing_owner_blocks(self):
        self.assertEqual(check([user("finance", False, "FINANCE")])
                         ["status"], "blocked")

    def test_duplicate_case_insensitive_login_blocks(self):
        self.assertEqual(check([user(), user("SERKAN", False)])
                         ["issue_codes"], ("invalid_or_duplicate_login",))

    def test_string_false_is_not_a_boolean(self):
        self.assertEqual(check([user(), user("finance", "false", "FINANCE")])
                         ["issue_codes"], ("explicit_boolean_enabled_required",))

    def test_plaintext_fallback_blocks_even_for_disabled_user(self):
        accounts = [user(), {**user("finance", False, "FINANCE"),
                             "password": "synthetic-only"}]
        self.assertEqual(check(accounts)["issue_codes"],
                         ("plaintext_password_present",))

    def test_legacy_fallback_blocks(self):
        self.assertEqual(check(legacy=True)["issue_codes"],
                         ("legacy_password_fallback_present",))

    def test_missing_or_bad_hash_blocks(self):
        for bad in ("", "plaintext", "pbkdf2_sha256$1$" + "a" * 32 + "$" + "b" * 64):
            with self.subTest(bad=bad[:8]):
                self.assertEqual(check([user(password_hash=bad)])["status"], "blocked")

    def test_signing_key_rejects_missing_short_and_repetitive(self):
        for key in ("", "abc", "a" * 40):
            with self.subTest(key=key[:8]):
                self.assertEqual(check(key=key)["status"], "blocked")

    def test_invalid_registry_and_owner_login(self):
        self.assertEqual(review("{", KEY, "serkan")["status"], "blocked")
        self.assertEqual(review("[]", KEY, "serkan")["status"], "blocked")
        self.assertEqual(check(owner="Serkan")["status"], "blocked")

    def test_dict_users_form_supported(self):
        self.assertEqual(review(json.dumps({"users": [user()]}), KEY, "serkan")
                         ["status"], "review_required")


if __name__ == "__main__":
    unittest.main()
