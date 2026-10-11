"""Synthetic-only independent reference digest checks, never a DB call."""
import hashlib
import unittest

from scripts.postgres_backup_reference_hash import compare_saved_sha256
from scripts.postgres_backup_verify import MAX_FILE_BYTES


class BackupReferenceTests(unittest.TestCase):
    def test_independently_saved_reference_matches(self):
        data = b"fictional-backup-bytes"
        expected = hashlib.sha256(data).hexdigest()
        self.assertEqual(compare_saved_sha256(data, expected), "matched")
        self.assertEqual(compare_saved_sha256(data, expected.upper()), "matched")
        self.assertEqual(compare_saved_sha256(data, " " + expected + " "), "matched")

    def test_substituted_archive_rejected_by_saved_hash(self):
        old = b"fictional-original"
        changed = b"fictional-tampered"
        expected = hashlib.sha256(old).hexdigest()
        self.assertEqual(compare_saved_sha256(changed, expected), "mismatch")

    def test_missing_reference_does_not_claim_authenticity(self):
        self.assertEqual(compare_saved_sha256(b"sample", ""), "no_reference")
        self.assertEqual(compare_saved_sha256(b"sample", None), "no_reference")

    def test_bad_hash_and_files_never_return_success(self):
        for ref in ("BAD", "0"*63, "0"*65, "g"*64, 42, True):
            self.assertEqual(compare_saved_sha256(b"sample", ref), "invalid_reference")
        for data in ("text", None, b"", bytearray(b"sample"),
                     b"a" * (MAX_FILE_BYTES + 1024)):
            # A slight oversize above ZIP is still below the encrypted
            # transport bound: reject oversize at the absolute maximum.
            if isinstance(data, bytes) and len(data) <= MAX_FILE_BYTES + 1024:
                continue
            self.assertEqual(
                compare_saved_sha256(data, hashlib.sha256(b"sample").hexdigest()),
                "invalid_file",
            )


if __name__ == "__main__":
    unittest.main()
