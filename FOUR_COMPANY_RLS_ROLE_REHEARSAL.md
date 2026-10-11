# CI-only four-company PostgreSQL RLS role test

This change does not touch live Supabase, RLS policies, grants or data.
It is an experiment in a temporary GitHub Actions PostgreSQL database,
inside a transaction deliberately rolled back at the end.

## Scope

- Four **fictional** database roles `ct_ci_rls_a/b/c/d` are created
  with `NOLOGIN`, `NOINHERIT`, `NOSUPERUSER`, `NOBYPASSRLS`.
- A dedicated temporary `ct_ci_four_company_rls_only` schema gets
  synthetic document records for four fictional legal entities.
- RLS SELECT/INSERT policies require explicit read/write DB grants
  with `principal_id=current_user` AND
  `g.legal_entity_id=demo_documents.legal_entity_id`.
- The test checks A reads A, D reads D, B/C see no records;
  A can insert only into A, D is read-only, cross-company inserts
  fail, and all fake roles/objects vanish after transaction rollback.

## Security boundaries and missing work

This deliberately uses PostgreSQL's **current database role**, not a
user-supplied `current_setting('app.company')` value. A client who can
SET ROLE to another tenant or a privileged/superuser database connection
would bypass the intended boundary. `FORCE ROW LEVEL SECURITY` does
**not** prevent a PostgreSQL superuser or a role with BYPASSRLS privilege
from bypassing RLS.

The current Streamlit application uses a shared PostgreSQL connection
and is **not** mapped to these fictitious roles. Therefore this CI test
cannot be treated as a production-ready RLS architecture, nor can this
policy SQL be safely copied to live `ct_app`.

The next security design must use independently authenticated users and
unforgeable mapped least-privilege PostgreSQL principals, audited role
switch permissions, secured group-company grants, 26-table CRM/finance
access paths, provider API exposed-schema configuration, and
single-company compositional write transactions.

A full, independently RESTORED recent Supabase backup and explicit
production approval are required before any company migration or
service-role changes. No live RLS, DDL, auth or backup calls are made.
