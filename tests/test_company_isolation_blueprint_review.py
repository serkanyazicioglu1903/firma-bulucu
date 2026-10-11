"""26-table four-company policy review: offline synthetic inputs only."""
import copy
from pathlib import Path
import unittest

from scripts.company_isolation_blueprint_review import review_isolation_blueprint
from scripts.group_company_catalog import COMPANY_LABELS
from scripts.postgres_company_full_coverage import REVIEW_GROUPS, _catalog_tables


def sample_blueprint():
    """Only fictional registration and evidence references; no real records."""
    companies = [
        {
            "code": code,
            "legal_name": "Example Registered Legal Name " + str(index),
            "evidence_ref": "REVIEW-DOC-2026-" + str(index),
        }
        for index, code in enumerate(COMPANY_LABELS, 1)
    ]
    tables = []
    for group, names in REVIEW_GROUPS.items():
        for table in names:
            mode = ("shared_candidate" if group == "shared_master_decision"
                    else "internal_only" if group == "internal_access_decision"
                    else "direct_owner")
            tables.append({
                "table": table,
                "mode": mode,
                "parent_table": None,
                "fk_column": None,
                "evidence_ref": "ARCH-REVIEW-2026",
            })
    return {"companies": companies, "tables": tables}


def table_for(blueprint, name):
    return next(p for p in blueprint["tables"] if p["table"] == name)


def link(blueprint, child, parent, fk):
    row = table_for(blueprint, child)
    row.update(mode="parent_scoped", parent_table=parent, fk_column=fk)


class CompanyIsolationBlueprintTests(unittest.TestCase):
    def test_all_26_tables_are_explicit_and_even_complete_is_not_approval(self):
        blueprint = sample_blueprint()
        self.assertEqual(len(_catalog_tables()), 26)
        report = review_isolation_blueprint(blueprint)
        self.assertEqual(report["status"], "review_required")
        self.assertEqual(report["reviewed_table_count"], 26)
        self.assertEqual(report["reviewed_company_count"], 4)
        self.assertEqual(report["proposed_shared_candidates"], 1)
        self.assertEqual(report["proposed_internal_only_tables"], 2)
        for key in (
            "company_isolation_verified", "database_constraints_verified",
            "row_level_access_verified", "legal_register_verified",
            "production_approved",
        ):
            self.assertIs(report[key], False)

    def test_parent_chain_requires_direct_owner(self):
        manifest = sample_blueprint()
        link(manifest, "contacts", "customers", "customer_id")
        link(manifest, "activities", "contacts", "contact_id")
        report = review_isolation_blueprint(manifest)
        self.assertEqual(report["status"], "review_required")
        self.assertEqual(report["proposed_parent_scoped_tables"], 2)

    def test_missing_duplicate_and_unknown_table_denied(self):
        for action in ("missing", "duplicate", "unknown"):
            with self.subTest(action=action):
                manifest = sample_blueprint()
                if action == "missing":
                    manifest["tables"].pop()
                if action == "duplicate":
                    manifest["tables"][-1] = copy.deepcopy(manifest["tables"][0])
                if action == "unknown":
                    manifest["tables"][-1]["table"] = "shadow_payments"
                self.assertEqual(review_isolation_blueprint(manifest)["status"],
                                 "blocked")

    def test_critical_tables_must_be_direct_owned_even_with_parent(self):
        m = sample_blueprint()
        link(m, "shipments", "purchase_orders", "purchase_order_id")
        report = review_isolation_blueprint(m)
        self.assertEqual(report["issue_codes"], ("invalid_table_policy",))

    def test_parent_cannot_inherit_shared_or_internal_access(self):
        for parent in ("product_catalog", "audit_log"):
            with self.subTest(parent=parent):
                m = sample_blueprint()
                link(m, "inventory_policy", parent, "product_id")
                self.assertEqual(
                    review_isolation_blueprint(m)["issue_codes"],
                    ("parent_not_company_owned",),
                )

    def test_parent_cycle_and_bad_fk_denied(self):
        m = sample_blueprint()
        link(m, "contacts", "activities", "activity_id")
        link(m, "activities", "contacts", "contact_id")
        self.assertEqual(review_isolation_blueprint(m)["issue_codes"],
                         ("cyclic_parent_path",))
        m = sample_blueprint()
        link(m, "contacts", "customers", 'customer_id;DROP TABLE')
        self.assertEqual(review_isolation_blueprint(m)["issue_codes"],
                         ("invalid_parent_path",))

    def test_no_company_wildcard_missing_identity_duplicate_or_fake_evidence(self):
        for operation in ("missing", "duplicate", "wildcard", "no_evidence"):
            with self.subTest(operation=operation):
                m = sample_blueprint()
                if operation == "missing":
                    m["companies"].pop()
                if operation == "duplicate":
                    m["companies"][-1] = copy.deepcopy(m["companies"][0])
                if operation == "wildcard":
                    m["companies"][-1]["code"] = "*"
                if operation == "no_evidence":
                    m["companies"][-1]["evidence_ref"] = ""
                self.assertEqual(review_isolation_blueprint(m)["status"],
                                 "blocked")

    def test_no_secret_user_supplied_content_is_returned(self):
        m = sample_blueprint()
        m["companies"][0]["legal_name"] = "PRIVATE CORPORATE RECORD 123"
        m["companies"][0]["evidence_ref"] = "FILE-PRIVATE123"
        report = review_isolation_blueprint(m)
        self.assertNotIn("PRIVATE", str(report))
        self.assertEqual(report["status"], "review_required")

    def test_no_implicit_sharing_for_finance_or_crm(self):
        for table in ("finance_transactions", "cash_accounts",
                      "receivables", "payables", "quotes", "customers"):
            with self.subTest(table=table):
                m = sample_blueprint()
                table_for(m, table)["mode"] = "shared_candidate"
                self.assertEqual(review_isolation_blueprint(m)["status"],
                                 "blocked")

    def test_never_imports_secrets_database_or_changes_schema(self):
        source = (Path(__file__).resolve().parents[1] / "scripts"
                  / "company_isolation_blueprint_review.py").read_text()
        for forbidden in ("psycopg", "sqlite3", "os.environ",
                          "INSERT INTO", "ALTER TABLE", "GRANT ", "COMMIT"):
            self.assertNotIn(forbidden, source)


if __name__ == "__main__":
    unittest.main()
