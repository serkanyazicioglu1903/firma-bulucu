"""Static tests: no production DDL, writes, secrets or data imports."""
import unittest
from scripts.postgres_company_scope import CRITICAL_TABLES
from scripts.postgres_legal_entity_rehearsal import (
    OWNED_RELATIONSHIPS, PARENTS, additive_ddl, enforcement_ddl,
)


class LegalEntityRehearsalTests(unittest.TestCase):
    def test_additive_ddl_never_assigns_legacy_ownership(self):
        sql = additive_ddl()
        self.assertEqual(len(sql), 1 + 2 * len(CRITICAL_TABLES))
        self.assertIn('CREATE TABLE "ct_app"."legal_entities"', sql[0])
        for table in CRITICAL_TABLES:
            self.assertIn(
                f'ALTER TABLE "ct_app"."{table}" ADD COLUMN legal_entity_id '
                'BIGINT NULL REFERENCES "ct_app"."legal_entities"(id)',
                sql,
            )
        self.assertNotIn("INSERT ", " ".join(sql))
        self.assertNotIn("UPDATE ", " ".join(sql))
        self.assertNotIn("DROP ", " ".join(sql))

    def test_enforcement_requires_owner_and_composite_fk(self):
        sql = enforcement_ddl()
        self.assertEqual(
            len(sql), len(PARENTS) + len(CRITICAL_TABLES) + len(OWNED_RELATIONSHIPS)
        )
        for table in CRITICAL_TABLES:
            self.assertIn(
                f'ALTER TABLE "ct_app"."{table}" '
                'ALTER COLUMN legal_entity_id SET NOT NULL', sql,
            )
        for child, col, parent in OWNED_RELATIONSHIPS:
            self.assertIn(
                f'FOREIGN KEY ({col}, legal_entity_id) '
                f'REFERENCES "ct_app"."{parent}" (id, legal_entity_id)',
                "\n".join(sql),
            )
        self.assertNotIn("DISABLE TRIGGER", " ".join(sql))
        self.assertNotIn("DROP ", " ".join(sql))

    def test_no_automatic_migration_or_import_entrypoint(self):
        from scripts import postgres_legal_entity_rehearsal as mod
        self.assertFalse(hasattr(mod, "apply_migration"))
        self.assertFalse(hasattr(mod, "connect"))
        self.assertFalse(hasattr(mod, "main"))


if __name__ == "__main__":
    unittest.main()
