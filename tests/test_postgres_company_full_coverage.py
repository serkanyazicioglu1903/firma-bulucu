"""Read-only, complete 26-table legal-ownership inventory tests."""
import unittest
from unittest.mock import MagicMock
from scripts import postgres_company_full_coverage as q


def fixture_rows(owner_for_critical=False, rls=False):
    critical = set(q.REVIEW_GROUPS["direct_owner_required"])
    return [
        (name, owner_for_critical and name in critical,
         owner_for_critical and name in critical, rls)
        for name in sorted(q._catalog_tables())
    ]


class CompanyFullCoverageTests(unittest.TestCase):
    def test_every_real_schema_table_has_one_review_classification(self):
        actual = q._catalog_tables()
        self.assertEqual(len(actual), 26)
        self.assertEqual(sum(map(len, q.REVIEW_GROUPS.values())), 26)
        self.assertIn("customers", q.REVIEW_GROUPS["parent_ownership_decision"])
        self.assertIn("cash_events", q.REVIEW_GROUPS["derived_ownership_decision"])

    def test_current_legacy_shape_fails_closed(self):
        report = q.classify_catalog_rows(fixture_rows())
        self.assertEqual(report["status"], "ownership_structure_incomplete")
        self.assertEqual(len(report["missing_required_owner"]), 8)
        self.assertEqual(report["table_count"], 26)
        self.assertEqual(len(report["tables_needing_design_review"]), 18)
        self.assertFalse(report["four_company_isolation_verified"])

    def test_eight_owned_tables_do_not_certify_other_eighteen(self):
        report = q.classify_catalog_rows(
            fixture_rows(owner_for_critical=True, rls=True)
        )
        self.assertEqual(report["required_nonnull_owner_count"], 8)
        self.assertEqual(report["rls_enabled_count"], 26)
        self.assertEqual(report["status"], "review_required")
        self.assertEqual(len(report["tables_needing_design_review"]), 18)
        self.assertFalse(report["live_migration_approved"])

    def test_nullable_owner_is_not_good_enough(self):
        rows = fixture_rows(owner_for_critical=True)
        name = q.REVIEW_GROUPS["direct_owner_required"][0]
        rows = [(n, yes, False if n == name else nn, rls)
                for n, yes, nn, rls in rows]
        report = q.classify_catalog_rows(rows)
        self.assertEqual(report["status"], "ownership_structure_incomplete")
        self.assertIn(name, report["nullable_required_owner"])

    def test_rejects_missing_duplicate_unknown_and_fake_flags(self):
        rows = fixture_rows()
        for wrong in (
            rows[:-1], rows + [rows[0]],
            rows[:-1] + [("never_created", False, False, False)],
            rows[:-1] + [(rows[-1][0], 1, False, False)],
            rows[:-1] + [(rows[-1][0], False, True, False)],
        ):
            self.assertNotEqual(q.classify_catalog_rows(wrong)["table_count"], 26)

    def test_cursor_only_queries_metadata_not_business_rows(self):
        cur = MagicMock()
        cur.fetchall.return_value = fixture_rows()
        report = q.inspect_catalog_on_cursor(cur)
        self.assertEqual(report["table_count"], 26)
        query = cur.execute.call_args.args[0]
        self.assertIn("pg_class", query)
        self.assertNotIn("FROM ct_app.", query)
        self.assertEqual(cur.execute.call_args.args[1][0], "ct_app")

    def test_invalid_connection_never_opens_database(self):
        report = q.inspect_live_company_ownership("not-a-postgres-url")
        self.assertEqual(report["status"], "invalid_url")
        self.assertFalse(report["four_company_isolation_verified"])


if __name__ == "__main__":
    unittest.main()
