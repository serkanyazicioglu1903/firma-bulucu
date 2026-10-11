"""Offline regression coverage for downloaded AS Control Tower ZIP inspection.

All files synthetic and in-memory. No server connections, no real business data.
"""
import hashlib
from io import BytesIO
import json
import unittest
import zipfile

from scripts.postgres_backup_verify import inspect_export_zip
from tests.test_postgres_restore_drill import zip_sample


class DownloadedExportVerificationTests(unittest.TestCase):
    def test_valid_empty_archive_has_26_verified_checksums(self):
        payload, names = zip_sample()
        status, report = inspect_export_zip(payload)
        self.assertEqual(status, "verified_format")
        self.assertEqual(report["table_count"], 26)
        self.assertEqual(report["row_count"], 0)
        self.assertEqual(set(report["table_counts"]), set(names))
        self.assertFalse(report["restoration_tested"])
        self.assertEqual(report["sha256"], hashlib.sha256(payload).hexdigest())
        self.assertNotIn("rows", report)

    def test_reject_bad_manifest_extra_files_and_wrong_checksums(self):
        for payload in (
            b"not-zip",
            zip_sample(tamper="wrong_schema")[0],
            zip_sample(tamper="wrong_checksum")[0],
            zip_sample(additional_file=True)[0],
        ):
            with self.subTest(bytes=len(payload)):
                status, report = inspect_export_zip(payload)
                self.assertEqual(status, "corrupt_or_wrong_format")
                self.assertIsNone(report)

    def test_reject_invalid_payload_sizes(self):
        for payload in (None, "text", b"", b"X" * (30 * 1024 * 1024 + 1)):
            with self.subTest(size=len(payload) if isinstance(payload, bytes) else 0):
                status, report = inspect_export_zip(payload)
                self.assertEqual((status, report), ("invalid_file", None))

    def test_bad_record_columns_rejected_even_with_correct_checksum(self):
        payload, names = zip_sample()
        with zipfile.ZipFile(BytesIO(payload)) as original:
            manifest = json.loads(original.read("manifest.json"))
            archive_rows = {
                name: original.read("tables/" + name + ".json")
                for name in names
            }
        # The checksum is legitimate: this test is for a malformed business
        # row that lacks required schema columns, not only ZIP corruption.
        data = json.dumps([{"id": 1, "name": "FICTIONAL ONLY"}]).encode()
        manifest["tables"]["customers"] = {
            "sha256": hashlib.sha256(data).hexdigest(),
            "row_count": 1,
        }
        archive_rows["customers"] = data
        out = BytesIO()
        with zipfile.ZipFile(out, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            archive.writestr("manifest.json", json.dumps(manifest))
            for name in names:
                archive.writestr("tables/" + name + ".json", archive_rows[name])
        self.assertEqual(
            inspect_export_zip(out.getvalue()), ("corrupt_or_wrong_format", None)
        )


if __name__ == "__main__":
    unittest.main()
