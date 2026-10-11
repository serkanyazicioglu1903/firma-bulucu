"""Tests for opt-in encrypted scheduled backups; uses only synthetic ZIP data.

Never touches live Supabase, secrets, GitHub artifacts or any customer records.
"""
from io import StringIO
from contextlib import redirect_stdout
import os
from pathlib import Path
import stat
import tempfile
import unittest
from unittest.mock import patch

from scripts import scheduled_encrypted_backup as backup
from scripts.postgres_encrypted_backup import (
    decrypt_export_zip, inspect_encrypted_export,
)
from tests.test_postgres_restore_drill import zip_sample

PASS = "Only-In-Offline-CI-Synthetic-BACKUP-KEY!"
DUMMY_URL = "postgresql://ci-fake@127.0.0.1/not-connected"


class ScheduledEncryptedBackupTests(unittest.TestCase):
    def test_synthetic_export_is_encrypted_and_decrypt_verified(self):
        archive, _ = zip_sample()
        with patch.object(
            backup, "export_postgres_backup", return_value=("ok", archive)
        ) as exporter:
            status, ciphertext, summary = backup.generate_encrypted_backup(
                DUMMY_URL, PASS
            )
        exporter.assert_called_once_with(DUMMY_URL)
        self.assertEqual(status, "ok")
        self.assertTrue(ciphertext.startswith(b"ASCTENC1"))
        self.assertNotIn(archive, ciphertext)
        self.assertNotIn(PASS.encode(), ciphertext)
        self.assertEqual(summary["tables"], 26)
        self.assertEqual(summary["rows"], 0)
        self.assertEqual(
            inspect_encrypted_export(ciphertext, PASS)[0], "verified_encrypted"
        )
        self.assertEqual(decrypt_export_zip(ciphertext, PASS)[1], archive)
        self.assertNotIn("password", str(summary).lower())

    def test_weak_key_rejected_before_private_database_is_read(self):
        with patch.object(backup, "export_postgres_backup") as exporter:
            result = backup.generate_encrypted_backup(DUMMY_URL, "aaaaaaaaaaaaaaa")
        self.assertEqual(result, ("weak_passphrase", None, None))
        exporter.assert_not_called()

    def test_invalid_export_never_produces_an_artifact(self):
        with patch.object(
            backup, "export_postgres_backup", return_value=("failed", None)
        ):
            self.assertEqual(
                backup.generate_encrypted_backup(DUMMY_URL, PASS),
                ("backup_failed", None, None),
            )
        self.assertEqual(
            backup.generate_encrypted_backup("", PASS),
            ("missing_configuration", None, None),
        )

    def test_written_backup_is_private_and_cannot_overwrite(self):
        with tempfile.TemporaryDirectory() as temp:
            destination = Path(temp) / "snapshot.asct"
            backup.write_encrypted_artifact(b"SYNTHETIC-CIPHERTEXT", destination)
            self.assertEqual(destination.read_bytes(), b"SYNTHETIC-CIPHERTEXT")
            self.assertEqual(stat.S_IMODE(destination.stat().st_mode), 0o600)
            with self.assertRaises(ValueError):
                backup.write_encrypted_artifact(b"NEW-BYTES", destination)
            self.assertEqual(destination.read_bytes(), b"SYNTHETIC-CIPHERTEXT")

    def test_actions_secrets_are_step_scoped_and_job_is_opt_in(self):
        workflow = (
            Path(__file__).resolve().parents[1]
            / ".github/workflows/opt-in-encrypted-backup.yml"
        ).read_text(encoding="utf-8")
        job_header = workflow.split("    steps:", 1)[0]
        self.assertIn("vars.CT_BACKUP_ENABLED == 'true'", job_header)
        self.assertNotIn("secrets.CT_BACKUP_DATABASE_URL", job_header)
        self.assertNotIn("secrets.CT_BACKUP_ENCRYPTION_PASSPHRASE", job_header)
        self.assertNotIn("runner.temp", job_header)
        self.assertIn("retention-days: 7", workflow)
        self.assertIn("if-no-files-found: error", workflow)
        self.assertEqual(workflow.count("${{ secrets.CT_BACKUP_DATABASE_URL }}"), 2)
        self.assertEqual(
            workflow.count("${{ secrets.CT_BACKUP_ENCRYPTION_PASSPHRASE }}"), 2
        )

    def test_disabled_workflow_cannot_request_postgres_export(self):
        out = StringIO()
        with patch.dict(os.environ, {"CT_BACKUP_ENABLED": "false"}):
            with patch.object(backup, "generate_encrypted_backup") as export:
                with redirect_stdout(out):
                    status = backup.main()
        self.assertEqual(status, 0)
        export.assert_not_called()
        self.assertIn("DISABLED", out.getvalue())

    def test_enabled_workflow_requires_secrets_and_does_not_print_them(self):
        out = StringIO()
        with patch.dict(
            os.environ,
            {
                "CT_BACKUP_ENABLED": "true",
                "CT_BACKUP_DATABASE_URL": "",
                "CT_BACKUP_ENCRYPTION_PASSPHRASE": "",
                "CT_BACKUP_OUTPUT_DIR": "",
            },
        ):
            with redirect_stdout(out):
                status = backup.main()
        self.assertEqual(status, 1)
        self.assertIn("missing_configuration", out.getvalue())

    def test_enabled_workflow_writes_only_verifiable_encrypted_artifact(self):
        archive, _ = zip_sample()
        with tempfile.TemporaryDirectory() as temp:
            with patch.dict(
                os.environ,
                {
                    "CT_BACKUP_ENABLED": "true",
                    "CT_BACKUP_DATABASE_URL": DUMMY_URL,
                    "CT_BACKUP_ENCRYPTION_PASSPHRASE": PASS,
                    "CT_BACKUP_OUTPUT_DIR": temp,
                },
            ):
                with patch.object(
                    backup, "export_postgres_backup", return_value=("ok", archive)
                ):
                    captured = StringIO()
                    with redirect_stdout(captured):
                        status = backup.main()
            self.assertEqual(status, 0, captured.getvalue())
            files = list(Path(temp).iterdir())
            self.assertEqual(len(files), 1)
            self.assertEqual(files[0].suffix, ".asct")
            self.assertEqual(stat.S_IMODE(files[0].stat().st_mode), 0o600)
            data = files[0].read_bytes()
            self.assertNotIn(archive, data)
            self.assertEqual(
                inspect_encrypted_export(data, PASS)[0], "verified_encrypted"
            )
            self.assertNotIn(DUMMY_URL, captured.getvalue())
            self.assertNotIn(PASS, captured.getvalue())
            self.assertIn("26 tables", captured.getvalue())


if __name__ == "__main__":
    unittest.main()
