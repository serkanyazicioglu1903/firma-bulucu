"""Synthetic-only encrypted backup roundtrip and tamper tests.

Never use real data, credentials, Supabase, GitHub artifacts or files on disk.
"""
import hashlib
import unittest

from scripts.postgres_encrypted_backup import (
    MAGIC, decrypt_export_zip, encrypt_export_zip, inspect_encrypted_export,
)
from tests.test_postgres_restore_drill import zip_sample

PASSWORD = "A-strong-private-sample-passphrase-2026!"


class EncryptedExportTests(unittest.TestCase):
    def test_valid_26_table_zip_encrypts_and_verifies(self):
        archive, _ = zip_sample()
        status, encrypted = encrypt_export_zip(archive, PASSWORD)
        self.assertEqual(status, "encrypted")
        self.assertTrue(encrypted.startswith(MAGIC))
        self.assertNotIn(PASSWORD.encode(), encrypted)
        self.assertNotIn(archive, encrypted)
        status, decrypted = decrypt_export_zip(encrypted, PASSWORD)
        self.assertEqual(status, "decrypted")
        self.assertEqual(decrypted, archive)
        status, summary = inspect_encrypted_export(encrypted, PASSWORD)
        self.assertEqual(status, "verified_encrypted")
        self.assertEqual(summary["table_count"], 26)
        self.assertEqual(summary["row_count"], 0)
        self.assertFalse(summary["restoration_tested"])
        self.assertEqual(
            summary["encrypted_sha256"],
            hashlib.sha256(encrypted).hexdigest(),
        )

    def test_random_salt_and_nonce_produce_unique_exports(self):
        archive, _ = zip_sample()
        a = encrypt_export_zip(archive, PASSWORD)
        b = encrypt_export_zip(archive, PASSWORD)
        self.assertEqual(a[0], "encrypted")
        self.assertEqual(b[0], "encrypted")
        self.assertNotEqual(a[1], b[1])
        self.assertEqual(decrypt_export_zip(a[1], PASSWORD)[1], archive)
        self.assertEqual(decrypt_export_zip(b[1], PASSWORD)[1], archive)

    def test_wrong_password_or_tampering_never_releases_data(self):
        archive, _ = zip_sample()
        _, encrypted = encrypt_export_zip(archive, PASSWORD)
        for ciphertext, password in (
            (encrypted, "wrong-password-with-length!!"),
            (encrypted[:-1] + bytes([encrypted[-1] ^ 1]), PASSWORD),
            (encrypted[:9] + bytes([encrypted[9] ^ 1]) + encrypted[10:], PASSWORD),
        ):
            with self.subTest(ciphertext_len=len(ciphertext)):
                status, payload = decrypt_export_zip(ciphertext, password)
                self.assertEqual(status, "wrong_password_or_corrupt")
                self.assertIsNone(payload)
                self.assertEqual(
                    inspect_encrypted_export(ciphertext, password)[1], None
                )

    def test_short_trivial_or_control_character_password_rejected(self):
        archive, _ = zip_sample()
        for password in ("", "tiny", "a" * 30, "PasswordHere\nSecond"):
            self.assertEqual(
                encrypt_export_zip(archive, password), ("weak_passphrase", None)
            )

    def test_invalid_zip_cannot_be_encrypted(self):
        self.assertEqual(
            encrypt_export_zip(b"not-an-archive", PASSWORD),
            ("invalid_archive", None),
        )

    def test_invalid_magic_file_and_size_are_rejected(self):
        for payload in (
            b"", b"wrong-format", b"ASCTENC1" + b"X" * 10,
            b"X" * (30 * 1024 * 1024 + 100),
        ):
            status, data = decrypt_export_zip(payload, PASSWORD)
            self.assertEqual(status, "invalid_file")
            self.assertIsNone(data)


if __name__ == "__main__":
    unittest.main()
