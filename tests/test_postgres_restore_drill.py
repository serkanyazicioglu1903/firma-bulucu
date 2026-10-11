"""Fail-closed backup drill tests; no real PostgreSQL connection is made."""
import hashlib
from io import BytesIO
import json
import os
import unittest
from unittest.mock import patch
import zipfile

from scripts.postgres_live_schema import schema_ddl_steps
from scripts.postgres_restore_drill import (
    _parse_and_verify_zip, verify_disposable_backup_restore,
)

LOCAL_URL = "postgresql://ct_ci:ci-dummy-only@127.0.0.1:5432/ct_ci_control_tower"
PRODUCTION_URL = "postgresql://admin:sensitive-secret@db.supabase.co:5432/postgres"


def zip_sample(*, tamper=None, additional_file=False):
    names, _, _ = schema_ddl_steps()
    manifest = {
        "format": "as-control-tower-ct-app-export-v1",
        "schema": "ct_app",
        "tables": {},
    }
    for name in names:
        data = b"[]"
        manifest["tables"][name] = {
            "sha256": hashlib.sha256(data).hexdigest(),
            "row_count": 0,
        }
    if tamper == "wrong_checksum":
        manifest["tables"][names[0]]["sha256"] = "0" * 64
    if tamper == "wrong_schema":
        manifest["schema"] = "public"
    out = BytesIO()
    with zipfile.ZipFile(out, mode="w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("manifest.json", json.dumps(manifest))
        for name in names:
            archive.writestr("tables/" + name + ".json", b"[]")
        if additional_file:
            archive.writestr("unexpected.txt", "Do not trust archive members")
    return out.getvalue(), names


class RestoreDrillGuardTests(unittest.TestCase):
    def test_even_explicit_ci_flag_cannot_restore_to_supabase(self):
        with patch.dict(os.environ, {"CT_LOCAL_POSTGRES_TEST": "1"}):
            result, data = verify_disposable_backup_restore(
                PRODUCTION_URL, zip_sample()[0]
            )
        self.assertEqual((result, data), ("forbidden", None))

    def test_ci_flag_off_rejects_localhost_too(self):
        with patch.dict(os.environ, {"CT_LOCAL_POSTGRES_TEST": "0"}):
            self.assertEqual(
                verify_disposable_backup_restore(LOCAL_URL, zip_sample()[0]),
                ("forbidden", None),
            )

    def test_exact_database_username_and_port_required(self):
        with patch.dict(os.environ, {"CT_LOCAL_POSTGRES_TEST": "1"}):
            for url in (
                "postgresql://ct_ci:test@127.0.0.1:5432/postgres",
                "postgresql://admin:test@127.0.0.1:5432/ct_ci_control_tower",
                "postgresql://ct_ci:test@127.0.0.1:6543/ct_ci_control_tower",
                "postgresql://ct_ci:test@192.168.0.4:5432/ct_ci_control_tower",
                LOCAL_URL + "?host=db.supabase.co",
                LOCAL_URL + "?hostaddr=192.168.0.4",
            ):
                with self.subTest(url=url):
                    self.assertEqual(
                        verify_disposable_backup_restore(url, b"archive"),
                        ("forbidden", None),
                    )

    def test_archive_verification_detects_corruption_or_extra_files(self):
        with patch.dict(os.environ, {"CT_LOCAL_POSTGRES_TEST": "1"}):
            for data in (
                b"bad-archive",
                zip_sample(tamper="wrong_checksum")[0],
                zip_sample(tamper="wrong_schema")[0],
                zip_sample(additional_file=True)[0],
            ):
                with self.subTest(size=len(data)):
                    self.assertEqual(
                        verify_disposable_backup_restore(LOCAL_URL, data),
                        ("invalid_archive", None),
                    )

    def test_valid_manifest_parses_without_database_side_effect(self):
        payload, names = zip_sample()
        parsed = _parse_and_verify_zip(payload, names)
        self.assertIsNotNone(parsed)
        batches, manifest = parsed
        self.assertEqual(set(batches), set(names))
        self.assertTrue(all(rows == [] for rows in batches.values()))
        self.assertEqual(manifest["schema"], "ct_app")


if __name__ == "__main__":
    unittest.main()
