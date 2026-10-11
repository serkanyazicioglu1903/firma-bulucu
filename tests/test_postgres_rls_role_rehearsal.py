"""Offline RLS policy checks and CI-negative authorization rehearsal."""
import unittest
from scripts import postgres_rls_role_rehearsal as q


class RoleBoundRlsTests(unittest.TestCase):
    def test_reviewed_statements_are_fixed_synthetic_schema_only(self):
        statements = q.review_sql()
        self.assertEqual(len(q.ROLES), 4)
        self.assertIn("ENABLE ROW LEVEL SECURITY", " ".join(statements))
        self.assertIn("FORCE ROW LEVEL SECURITY", " ".join(statements))
        self.assertIn("WITH CHECK", " ".join(statements))
        self.assertIn("NOBYPASSRLS", " ".join(statements))
        self.assertFalse(any(
            any(bad in stmt for bad in (
                "ct_app.", "supabase.", "postgres.", "CREATE USER",
                "CREATE EXTENSION", "ALTER ROLE postgres", "DROP TABLE",
            ))
            for stmt in statements
        ))
        self.assertTrue(all("ct_ci_" in stmt for stmt in statements))

    def test_policy_is_bound_to_current_database_role_and_outer_company(self):
        policy_sql = "\n".join(
            statement for statement in q.DDL
            if statement.startswith("CREATE POLICY")
        )
        self.assertIn("g.principal_id=current_user",policy_sql)
        self.assertIn(
            "g.legal_entity_id=demo_documents.legal_entity_id",policy_sql
        )
        self.assertNotIn("current_setting(",policy_sql)
        self.assertNotIn("g.legal_entity_id=legal_entity_id",policy_sql)
        self.assertIn("g.can_read=TRUE",policy_sql)
        self.assertIn("g.can_write=TRUE",policy_sql)

    def test_grant_defaults_do_not_allow_writes(self):
        ddls="\n".join(q.DDL)
        self.assertIn("can_read BOOLEAN NOT NULL DEFAULT FALSE",ddls)
        self.assertIn("can_write BOOLEAN NOT NULL DEFAULT FALSE",ddls)
        self.assertNotIn("GRANT ALL",ddls)
        self.assertNotIn("BYPASSRLS",ddls.replace("NOBYPASSRLS",""))


if __name__ == "__main__":
    unittest.main()
