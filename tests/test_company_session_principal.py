"""No secrets, no external accounts: signed company principals fail closed."""
import unittest
from unittest.mock import patch

from scripts import company_session_principal as principal

KEY = "ci-test-only-32-characters-secret-key-never-production"
CI_HASH = "pbkdf2_sha256$200000$" + "a" * 32 + "$" + "b" * 64
USERS = [{"username": "reviewer", "role": "FINANCE", "enabled": True,
          "password_hash": CI_HASH}]
SESSION = "ci-valid-session-1000"


class CompanyPrincipalTests(unittest.TestCase):
    def _secrets(self, name, default=""):
        return {
            "CT_COMPANY_SESSION_SIGNING_KEY": KEY,
            "APP_USERS_JSON": '[{"username":"reviewer"}]',
        }.get(name, default)

    @patch.object(principal, "load_users", return_value=USERS)
    @patch.object(principal, "_secret")
    def test_password_verified_login_can_sign_and_recheck(self, secret, users):
        secret.side_effect = self._secrets
        signature = principal.sign_verified_company_login(USERS[0], SESSION)
        self.assertIsInstance(signature, str)
        self.assertEqual(len(signature), 64)
        session = {"ct_session_id": SESSION, principal.SESSION_SIGNATURE_KEY: signature}
        with patch.object(principal, "current_user", return_value=USERS[0]):
            self.assertEqual(principal.verified_company_principal(session), "reviewer")
            session["ct_session_id"] = "forged-session"
            self.assertIsNone(principal.verified_company_principal(session))
            session["ct_session_id"] = SESSION
            session[principal.SESSION_SIGNATURE_KEY] = "0" * 64
            self.assertIsNone(principal.verified_company_principal(session))

    @patch.object(principal, "load_users", return_value=USERS)
    @patch.object(principal, "_secret")
    def test_admin_label_and_unverified_session_do_not_grant_scope(self, secret, users):
        secret.side_effect = self._secrets
        session = {"ct_session_id": SESSION, principal.SESSION_SIGNATURE_KEY: "0" * 64}
        with patch.object(principal, "current_user", return_value={
            "username": "reviewer", "role": "ADMIN"
        }):
            self.assertIsNone(principal.verified_company_principal(session))
        with patch.object(principal, "current_user", return_value=USERS[0]):
            self.assertIsNone(principal.verified_company_principal({"ct_session_id": SESSION}))

    @patch.object(principal, "load_users", return_value=USERS)
    @patch.object(principal, "_secret")
    def test_invalid_signing_key_and_missing_explicit_user_registry_block(self, secret, users):
        secret.side_effect = lambda name, default="": (
            "short" if name == "CT_COMPANY_SESSION_SIGNING_KEY"
            else '[{"username":"reviewer"}]'
        )
        self.assertIsNone(principal.sign_verified_company_login(USERS[0], SESSION))
        with patch.object(principal, "current_user", return_value=USERS[0]):
            self.assertIsNone(principal.verified_company_principal({}))
        secret.side_effect = lambda name, default="": (
            KEY if name == "CT_COMPANY_SESSION_SIGNING_KEY" else ""
        )
        self.assertIsNone(principal.sign_verified_company_login(USERS[0], SESSION))

    @patch.object(principal, "_secret")
    def test_password_hash_rotation_revokes_existing_signed_session(self, secret):
        secret.side_effect = self._secrets
        with patch.object(principal, "load_users", return_value=USERS):
            signature = principal.sign_verified_company_login(USERS[0], SESSION)
        self.assertIsInstance(signature, str)
        signed = {"ct_session_id": SESSION,
                  principal.SESSION_SIGNATURE_KEY: signature}
        replacement = dict(USERS[0], password_hash=(
            "pbkdf2_sha256$200000$" + "c" * 32 + "$" + "d" * 64
        ))
        with patch.object(principal, "current_user", return_value=USERS[0]):
            with patch.object(principal, "load_users", return_value=[replacement]):
                self.assertIsNone(principal.verified_company_principal(signed))
            with patch.object(principal, "load_users", return_value=USERS):
                self.assertEqual(principal.verified_company_principal(signed), "reviewer")

    @patch.object(principal, "_secret")
    def test_plaintext_or_missing_or_weak_hash_cannot_sign_company_session(self, secret):
        secret.side_effect = self._secrets
        for weak in (
            {"password": "plaintext", "password_hash": ""},
            {"password_hash": "pbkdf2_sha256$1000$" + "a"*32 + "$" + "b"*64},
            {"password_hash": "pbkdf2_sha256$200000$" + "wrong$" + "b"*64},
            {"password_hash": ""},
        ):
            account = {"username": "reviewer", "role": "FINANCE", "enabled": True, **weak}
            with patch.object(principal, "load_users", return_value=[account]):
                self.assertIsNone(principal.sign_verified_company_login(account, SESSION))

    @patch.object(principal, "_secret")
    def test_duplicate_enabled_username_is_ambiguous_and_denied(self, secret):
        secret.side_effect = self._secrets
        with patch.object(principal, "load_users", return_value=[USERS[0], USERS[0]]):
            self.assertIsNone(principal.sign_verified_company_login(USERS[0], SESSION))

    @patch.object(principal, "load_users", return_value=[
        {"username": "reviewer", "role": "FINANCE", "enabled": False, "password_hash": CI_HASH},
    ])
    @patch.object(principal, "_secret")
    def test_disabled_user_fails_even_with_previous_signature(self, secret, users):
        secret.side_effect = self._secrets
        fake = "f" * 64
        with patch.object(principal, "current_user", return_value=USERS[0]):
            self.assertIsNone(principal.verified_company_principal({
                "ct_session_id": SESSION, principal.SESSION_SIGNATURE_KEY: fake
            }))
        self.assertIsNone(principal.sign_verified_company_login(USERS[0], SESSION))


if __name__ == "__main__":
    unittest.main()
