import hashlib
import json
import os
from pathlib import Path
import tempfile
import tomllib
import unittest

from scripts.private_login_setup import login_settings, save_settings


class PrivateLoginSetupTests(unittest.TestCase):
    def test_settings_are_compatible_and_never_activate_runtime(self):
        password = 'Synthetic-test-password-123'
        text = login_settings(password, password)
        settings = tomllib.loads(text)
        self.assertEqual(set(settings), {'APP_USERS_JSON', 'CT_COMPANY_SESSION_SIGNING_KEY'})
        self.assertNotIn(password, text)
        users = json.loads(settings['APP_USERS_JSON'])['users']
        self.assertEqual(len(users), 1)
        self.assertEqual(users[0]['username'], 'serkan')
        algorithm, rounds, salt, digest = users[0]['password_hash'].split('$')
        self.assertEqual(algorithm, 'pbkdf2_sha256')
        self.assertEqual(hashlib.pbkdf2_hmac('sha256', password.encode(), salt.encode(), int(rounds)).hex(), digest)
        self.assertGreaterEqual(len(settings['CT_COMPANY_SESSION_SIGNING_KEY']), 32)
        self.assertNotEqual(text, login_settings(password, password))

    def test_invalid_passwords_rejected(self):
        for password, confirmation in [('short', 'short'), ('long-password-123', 'different')]:
            with self.assertRaises(ValueError):
                login_settings(password, confirmation)

    def test_private_file_cannot_overwrite_or_follow_symlink(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'settings.toml'
            save_settings(path, 'synthetic')
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)
            with self.assertRaises(FileExistsError):
                save_settings(path, 'replacement')
            link = Path(directory) / 'link.toml'
            link.symlink_to(path)
            with self.assertRaises(FileExistsError):
                save_settings(link, 'replacement')
            self.assertEqual(path.read_text(), 'synthetic')

    def test_repository_destination_rejected(self):
        with self.assertRaises(ValueError):
            save_settings(Path(__file__).parent / 'must-not-exist.toml', 'synthetic')


if __name__ == '__main__':
    unittest.main()
