"""Owner-mapping manifest: exact coverage, evidence, drift and FK checks."""
import copy
import unittest
from unittest.mock import MagicMock, patch

from scripts import postgres_company_owner_mapping_preflight as p

HASH = "0" * 32


def example_graph():
    snapshot = {}
    for table in p.CRITICAL_TABLES:
        refs = {name: None for name, _ in p.PARENT_FKS[table]}
        snapshot[table] = (
            {"id": 11, "row_hash": HASH, **{
                name: 11 for name in refs}},
            {"id": 12, "row_hash": "f" * 32, **{
                name: 12 for name in refs}},
        )
    return snapshot


def reviewed_plan(graph):
    return {
        "source_sha256": p.snapshot_digest(graph),
        "allocations": {
            table: [
                {"record_id": 11, "company_code": "AS_ILERI_GIDA",
                 "evidence_ref": "REVIEW_DOC_A_2026"},
                {"record_id": 12, "company_code": "AS_FOOD_GLOBAL",
                 "evidence_ref": "REVIEW_DOC_D_2026"},
            ]
            for table in p.CRITICAL_TABLES
        },
    }


class OwnerMappingPreflightTests(unittest.TestCase):
    def setUp(self):
        self.graph = example_graph()
        self.plan = reviewed_plan(self.graph)

    def test_full_human_review_still_not_automatically_approved(self):
        result = p.evaluate_owner_mapping(self.graph, self.plan)
        self.assertEqual(result["status"], "review_required")
        self.assertFalse(result["isolation_verified"])
        self.assertFalse(result["auto_assigned"])
        self.assertTrue(result["manual_approval_required"])
        self.assertTrue(result["source_fingerprint_matches"])
        self.assertEqual(result["checked_tables"], 8)
        self.assertEqual(result["checked_rows"], 16)
        self.assertEqual(result["issue_codes"], ())

    def test_changed_source_any_row_or_value_blocks_manifest(self):
        changed = copy.deepcopy(self.graph)
        changed["cash_accounts"][0]["row_hash"] = "a" * 32
        result = p.evaluate_owner_mapping(changed, self.plan)
        self.assertEqual(result["status"], "blocked")
        self.assertIn("stale_or_invalid_source", result["issue_codes"])
        self.assertFalse(result["source_fingerprint_matches"])

    def test_missing_extra_and_duplicate_rows_are_rejected(self):
        variants = []
        missing = copy.deepcopy(self.plan)
        missing["allocations"]["cash_accounts"].pop()
        variants.append(missing)
        duplicate = copy.deepcopy(self.plan)
        duplicate["allocations"]["payables"].append(
            duplicate["allocations"]["payables"][0].copy()
        )
        variants.append(duplicate)
        unknown = copy.deepcopy(self.plan)
        unknown["allocations"]["shipments"][0]["record_id"] = 987
        variants.append(unknown)
        for plan in variants:
            with self.subTest(plan=plan):
                result = p.evaluate_owner_mapping(self.graph, plan)
                self.assertEqual(result["status"], "blocked")
                self.assertTrue(result["issue_codes"])

    def test_unverified_company_and_missing_evidence_block(self):
        invalid_company=copy.deepcopy(self.plan)
        invalid_company["allocations"]["receivables"][0]["company_code"] = "UNKNOWN"
        result=p.evaluate_owner_mapping(self.graph,invalid_company)
        self.assertIn("invalid_allocations",result["issue_codes"])
        no_evidence=copy.deepcopy(self.plan)
        no_evidence["allocations"]["purchase_orders"][0]["evidence_ref"]=""
        result=p.evaluate_owner_mapping(self.graph,no_evidence)
        self.assertIn("invalid_allocations",result["issue_codes"])

    def test_cross_company_shipment_and_bank_settlement_relationship_block(self):
        conflict=copy.deepcopy(self.plan)
        conflict["allocations"]["shipments"][0]["company_code"]="AS_FOOD_GLOBAL"
        result=p.evaluate_owner_mapping(self.graph,conflict)
        self.assertEqual(result["status"],"blocked")
        self.assertIn("cross_company_relation",result["issue_codes"])

        wrong_bank=copy.deepcopy(self.plan)
        wrong_bank["allocations"]["cash_accounts"][0]["company_code"]="AS_FOOD_GLOBAL"
        result=p.evaluate_owner_mapping(self.graph,wrong_bank)
        self.assertIn("cross_company_relation",result["issue_codes"])

    def test_missing_parent_and_empty_source_never_approve(self):
        orphan=copy.deepcopy(self.graph)
        orphan["finance_transactions"][0]["account_id"]=999
        plan=reviewed_plan(orphan)
        result=p.evaluate_owner_mapping(orphan,plan)
        self.assertIn("missing_parent_record",result["issue_codes"])
        empty={table: () for table in p.CRITICAL_TABLES}
        result=p.evaluate_owner_mapping(empty,{
            "source_sha256":p.snapshot_digest(empty),
            "allocations":{table:[] for table in p.CRITICAL_TABLES},
        })
        self.assertIn("empty_source_not_tested",result["issue_codes"])

    def test_bad_snapshot_and_bad_manifest_are_redacted(self):
        self.assertEqual(
            p.evaluate_owner_mapping({"cash_accounts":[]},self.plan)["issue_codes"],
            ("invalid_snapshot",),
        )
        wrong=copy.deepcopy(self.graph)
        wrong["cash_accounts"][0]["row_hash"]="malformed"
        self.assertIn("invalid_snapshot",p.evaluate_owner_mapping(wrong,self.plan)["issue_codes"])
        result=p.evaluate_owner_mapping(self.graph,None)
        self.assertEqual(result["issue_codes"],("stale_or_invalid_source",))
        self.assertNotIn("REVIEW_DOC",str(result))
        self.assertNotIn("AS_FOOD_GLOBAL",str(result))

    def test_read_only_query_is_fixed_allowlisted_and_bounded(self):
        cur=MagicMock()
        cur.fetchall.return_value=[(11,HASH,*([None]*2))]
        graph=p.read_owner_graph_on_cursor(cur)
        self.assertEqual(set(graph),set(p.CRITICAL_TABLES))
        self.assertEqual(cur.execute.call_count,8)
        for call in cur.execute.call_args_list:
            stmt,params=call.args
            self.assertTrue(stmt.startswith("SELECT t.id, md5(row_to_json(t)::text)"))
            self.assertEqual(params,(p.MAX_TABLE_ROWS+1,))
            self.assertNotIn("INSERT ",stmt)
            self.assertNotIn("UPDATE ",stmt)
            self.assertNotIn("DELETE ",stmt)

    @patch("psycopg.connect")
    def test_invalid_db_url_never_opens_connection(self, connect):
        self.assertEqual(p.read_owner_graph("sqlite:///demo.db"),("invalid_url",None))
        connect.assert_not_called()


if __name__ == "__main__":
    unittest.main()
