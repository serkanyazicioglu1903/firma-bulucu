"""Read-only 26-table recovery baseline must fail closed and never approve cutover."""
from copy import deepcopy
import hashlib
import json
import unittest
from unittest.mock import MagicMock, patch

from scripts import postgres_recovery_baseline as recovery


def mock_live_baseline(*, flags=None, extra=None, counts=None):
    names = recovery._expected()
    rows = [(name, False, False, False, False) for name in names]
    if flags:
        table, position = flags
        idx = names.index(table)
        row = list(rows[idx])
        row[position] = True
        rows[idx] = tuple(row)
    if extra:
        rows.append((extra, False, False, False, False))
    columns = [(name, "id", "bigint", True) for name in names]
    counts = counts or {}
    cursor = MagicMock()
    cursor.fetchall.side_effect = [rows, columns]
    cursor.fetchone.side_effect = [(counts.get(name, 0),) for name in names]
    return cursor


class RecoveryBaselineTests(unittest.TestCase):
    def test_26_table_legacy_baseline_counts_and_has_no_live_approval(self):
        cursor = mock_live_baseline(counts={
            "customers": 1, "contacts": 1, "audit_log": 2
        })
        result = recovery.capture_legacy_baseline_on_cursor(cursor)
        self.assertEqual(result["status"], "baseline_captured")
        self.assertEqual(result["tables"], 26)
        self.assertEqual(result["rows"], 4)
        self.assertEqual(result["counts"]["customers"], 1)
        self.assertEqual(result["counts"]["audit_log"], 2)
        self.assertEqual(len(result["counts"]), 26)
        self.assertEqual(len(result["counts_sha256"]), 64)
        self.assertEqual(len(result["schema_sha256"]), 64)
        self.assertFalse(result["provider_backup_verified"])
        self.assertFalse(result["provider_restore_verified"])
        self.assertFalse(result["production_cutover_approved"])
        self.assertEqual(cursor.execute.call_count, 28)
        statements = [call.args[0] for call in cursor.execute.call_args_list]
        self.assertTrue(all(str(s).startswith("SELECT ") for s in statements[:2]))
        from psycopg import sql
        self.assertTrue(all(isinstance(s, sql.Composed) for s in statements[2:]))
        self.assertTrue(all("pg_" in str(s) for s in statements[:2]))
        self.assertNotIn("WHERE id", " ".join(str(x) for x in statements))
        self.assertNotIn("SELECT *", " ".join(str(x) for x in statements))

    def test_schema_changes_and_active_company_migration_block_baseline(self):
        for kwargs, issue in (
            ({"extra": "company_read_grants"}, "schema_mismatch"),
            ({"flags": ("customers", 1)}, "company_migration_started"),
            ({"flags": ("customers", 3)}, "company_migration_started"),
            ({"flags": ("cash_accounts", 4)}, "company_migration_started"),
        ):
            with self.subTest(kwargs=kwargs):
                cursor = mock_live_baseline(**kwargs)
                report = recovery.capture_legacy_baseline_on_cursor(cursor)
                self.assertEqual(report["status"], issue)
                self.assertEqual(report["counts"], {})
                self.assertFalse(report["production_cutover_approved"])
                self.assertEqual(cursor.execute.call_count, 1)

    def test_unrecognized_schema_never_queries(self):
        cursor = MagicMock()
        self.assertEqual(
            recovery.capture_legacy_baseline_on_cursor(
                cursor, schema="public;DROP SCHEMA ct_app"
            )["status"], "invalid_schema"
        )
        cursor.execute.assert_not_called()

    def test_drift_or_corrupted_proposed_restore_summary_is_blocked(self):
        source = recovery.capture_legacy_baseline_on_cursor(
            mock_live_baseline(counts={"customers": 1, "contacts": 1})
        )
        restored = deepcopy(source)
        self.assertEqual(
            recovery.compare_isolated_restore_baselines(
                source, restored
            )["status"], "review_required"
        )
        # Evidence from an operator alone cannot establish a provider restore.
        self.assertFalse(
            recovery.compare_isolated_restore_baselines(
                source, restored
            )["provider_restore_verified"]
        )
        restored["counts"]["customers"] = 2
        self.assertEqual(
            recovery.compare_isolated_restore_baselines(
                source, restored
            )["status"], "invalid_evidence"
        )
        restored["counts_sha256"] = hashlib.sha256(
            json.dumps(restored["counts"], sort_keys=True,
                       separators=(",", ":")).encode()
        ).hexdigest()
        self.assertEqual(
            recovery.compare_isolated_restore_baselines(
                source, restored
            )["status"], "restore_mismatch"
        )
        self.assertFalse(
            recovery.compare_isolated_restore_baselines(
                source, restored
            )["production_cutover_approved"]
        )

    def test_column_drift_and_incomplete_source_cannot_pass(self):
        original = recovery.capture_legacy_baseline_on_cursor(
            mock_live_baseline()
        )
        changed = dict(original)
        changed["schema_sha256"] = "1" * 64
        result = recovery.compare_isolated_restore_baselines(
            original, changed
        )
        self.assertEqual(result["status"], "restore_mismatch")
        self.assertFalse(result["schema_match"])
        incomplete = dict(original)
        incomplete["counts"] = {"customers": 0}
        self.assertEqual(
            recovery.compare_isolated_restore_baselines(
                original, incomplete
            )["status"], "invalid_evidence"
        )

    @patch("psycopg.connect")
    def test_invalid_url_does_not_connect(self, connect):
        result = recovery.read_legacy_baseline("sqlite:///user.db")
        self.assertEqual(result["status"], "invalid_url")
        connect.assert_not_called()

    def test_source_only_reads_catalog_and_counts(self):
        from pathlib import Path
        source = (Path(__file__).resolve().parents[1] / "scripts" /
                  "postgres_recovery_baseline.py").read_text()
        self.assertNotIn("INSERT INTO", source)
        self.assertNotIn("UPDATE ct_app", source)
        self.assertNotIn("DROP TABLE", source)
        self.assertNotIn("GRANT ", source)
        self.assertIn("READ ONLY", source)


if __name__ == "__main__":
    unittest.main()
