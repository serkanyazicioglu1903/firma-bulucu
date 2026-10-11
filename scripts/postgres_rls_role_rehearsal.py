"""DISPOSABLE PostgreSQL RLS rehearsal, no live schema or user changes.

The roles, schema, policies, synthetic grants and test records are created
only inside an intentionally rolled-back PostgreSQL CI transaction.
These are NOT production policies. There is no application login mapping and
the existing Streamlit superuser/connection can bypass RLS: deploying these
statements to Supabase would NOT provide real tenant isolation.
"""
SCHEMA = "ct_ci_four_company_rls_only"
ROLES = ("ct_ci_rls_a", "ct_ci_rls_b", "ct_ci_rls_c", "ct_ci_rls_d")

# STATIC reviewed SQL only, never executed automatically during import.
DDL = (
    *(f"CREATE ROLE {role} NOLOGIN NOINHERIT NOSUPERUSER NOBYPASSRLS"
      for role in ROLES),
    f"CREATE SCHEMA {SCHEMA}",
    f"CREATE TABLE {SCHEMA}.company_read_grants "
    "(principal_id NAME NOT NULL, legal_entity_id INTEGER NOT NULL, "
    "can_read BOOLEAN NOT NULL DEFAULT FALSE, "
    "PRIMARY KEY (principal_id, legal_entity_id))",
    f"CREATE TABLE {SCHEMA}.company_write_grants "
    "(principal_id NAME NOT NULL, legal_entity_id INTEGER NOT NULL, "
    "can_write BOOLEAN NOT NULL DEFAULT FALSE, "
    "PRIMARY KEY (principal_id, legal_entity_id))",
    f"CREATE TABLE {SCHEMA}.demo_documents "
    "(id INTEGER PRIMARY KEY, legal_entity_id INTEGER NOT NULL, "
    "note TEXT NOT NULL)",
    f"GRANT USAGE ON SCHEMA {SCHEMA} TO " + ", ".join(ROLES),
    f"GRANT SELECT ON {SCHEMA}.company_read_grants, "
    f"{SCHEMA}.company_write_grants TO " + ", ".join(ROLES),
    f"GRANT SELECT, INSERT ON {SCHEMA}.demo_documents TO "
    + ", ".join(ROLES),
    f"ALTER TABLE {SCHEMA}.demo_documents ENABLE ROW LEVEL SECURITY",
    f"ALTER TABLE {SCHEMA}.demo_documents FORCE ROW LEVEL SECURITY",
    f"CREATE POLICY ci_company_read ON {SCHEMA}.demo_documents "
    "FOR SELECT USING (EXISTS (SELECT 1 FROM "
    f"{SCHEMA}.company_read_grants g WHERE g.principal_id=current_user "
    "AND g.legal_entity_id=legal_entity_id AND g.can_read=TRUE))",
    f"CREATE POLICY ci_company_write ON {SCHEMA}.demo_documents "
    "FOR INSERT WITH CHECK (EXISTS (SELECT 1 FROM "
    f"{SCHEMA}.company_write_grants g WHERE g.principal_id=current_user "
    "AND g.legal_entity_id=legal_entity_id AND g.can_write=TRUE))",
)


def review_sql():
    """Not an executable migration runner. Consumers must be CI isolated."""
    return DDL
