# AS Control Tower — 2026-10-11 live Supabase security baseline

## Read-only evidence, no business data exported

Project: `AS-CONTROL-TOWER`, Supabase region `eu-west-2`.
The authorized read-only metadata audit on 11 October 2026 found:

| Metric | Observed |
| --- | ---: |
| Existing `ct_app` application tables | 26 |
| Tables with RLS enabled | 0 |
| Tables with RLS policies | 0 |
| Critical `legal_entity_id` columns | 0 of 8 |
| `anon` direct table access with schema USAGE | 0 |
| `authenticated` direct table access with schema USAGE | 0 |
| `service_role` direct table access with schema USAGE | 0 |

**Important distinction:** RLS being off is a real defense-in-depth gap;
it does not, without privileges and schema USAGE, prove that an anon API
user can query those 26 tables. This audit found no direct grants for the
three examined API roles at that moment. Access grants, PostgreSQL roles,
Supabase publication/exposure, SECURITY DEFINER functions and application
server routes can change or introduce other access paths. No claim of
full tenant isolation can be made from this alone.

## Changes in this PR

- Fixed-schema, on-demand, **read-only** catalog inspection in a repeatable
  read transaction. Only pg_catalog/role privileges are read, not
  customers, supplier names, banking or financial amounts.
- Explicitly compare schema USAGE **and** table SELECT/INSERT/UPDATE/DELETE
  grants for `anon`, `authenticated` and `service_role`. Counts rather
  than identities and row contents are shown.
- Distinguish `rls_enabled`, `owner_columns`, `registry_tables`,
  and `current_session_elevated`. A privileged server DB role can bypass
  RLS and must be audited independently.
- Add ADMIN-only phone-friendly button in existing Control Tower to inspect
  these values and state that four-company production approval is **false**.
- Offline and disposable PostgreSQL regression tests; no live schema DDL,
  no GRANT/REVOKE, no RLS or backup provider changes.

## Phase gates before an explicit live authorization

1. Verify the four legal registrations, exact corporate names and entity IDs.
2. Acquire a current independently held encrypted **FULL** database/schema/
   grants backup, including company registry tables as they are introduced.
3. Demonstrate a separate **restore** and reconciled ledger counts; establish
   recovery point, retention and rollback responsibility.
4. Approve a human-reviewed, complete, immutable ownership mapping for the
   eight critical tables; resolve all shared customer/warehouse and bank
   ownership questions.
5. Rehearse RLS with a **restricted dedicated DB role** and PostgreSQL
   policies; confirm Supabase exposed schemas, role privileges, function
   execution rights and how Streamlit authenticates each user. No role can
   claim a different company through a user-controlled setting.
6. Refactor all legacy SQL routes and exports; independently test wrong-company
   reads and writes, cross-company FK, fraud and duplicate settlement.
7. Obtain named company accounting/IT acceptance plus explicit migration,
   production backup/restore and go-live authorization.

Merely enabling RLS with no policies may disable existing app access. No
production RLS policy is activated or proposed for automatic execution here.

Supabase documentation:
https://supabase.com/docs/guides/database/postgres/row-level-security

**Existing `ct_app` has a small amount of previously present non-financial
CRM/admin records. The audit used metadata only and did not export them.**
