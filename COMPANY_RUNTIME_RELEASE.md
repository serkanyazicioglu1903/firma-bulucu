# AS Control Tower — Company runtime, PR 87

This release connects the former CI-only operation handlers to an opt-in,
exclusive Streamlit workspace. It does not activate that workspace or change
production configuration by being imported. No live SQL was executed during development.

## Implemented

- Signed login is bound to one dedicated PostgreSQL LOGIN role, with current user
  equal to session user. Superuser, BYPASSRLS, ownership and inherited role access
  are rejected. Shared DATABASE_URL is never used by the new workspace.
- Invalid/duplicate account directories and string booleans fail closed.
- All 23 company tables have non-null owners, RLS and FORCE RLS; parent references
  include company ownership. Owner changes are forbidden even when a user can
  access both entities. Shared product catalogue is deliberate; old audit/settings
  tables have no app-role access. API roles are revoked during the proposed migration.
- Company-specific customer/contact, warehouse and account creation; purchase
  orders, shipment receipts, stock lots, quality holds/releases; AP/AR and bank
  payments/collections. Writes include atomic audit and durable request deduplication.
- Saved quote calculations use the existing Decimal economics engine, retain the
  full input/result snapshot, and create linked purchase orders and receivables.
  Invoicing here means an internal receivable record, not a statutory tax invoice.
- Company financial tables use NUMERIC, and document/name uniqueness is per company.
- Company dashboard preserves currency separation. Supplier discovery reuses the
  existing engine without opening legacy database screens; it sends no emails.
- Encrypted native pg_dump backup includes 33 runtime tables, RLS, constraints and
  sequences. Restore helper categorically refuses nonlocal/non-CI destinations.
- Single-column entry forms, company-scoped lookup lists, company-switch draft
  clearing and logout clearing. No automatic schema creation or demo seeding.

## Verification

The PR's PostgreSQL workflow tests actual, independent non-superuser connections,
not SET ROLE or mocked database queries. Tests cover the operational and quote
chains, RLS visibility and write denials, composite FK rejection, immutable owners,
revocation, duplicate requests, rollback on audit failure, and encrypted restore
into a second empty database with all 33 table contents and RLS policy counts
compared. The app workflow runs the full pytest suite as well as existing checks.

Synthetic credentials in tests belong only to the disposable GitHub Actions service.
Local PostgreSQL tests are skipped when that service is absent; they are not
counted as locally passed. Hardware Safari acceptance remains a separate live check.

## Concrete activation steps — require owner's separate approval

1. Merge this reviewed PR only after its exact commit has green app/PostgreSQL CI.
2. Take and independently restore a current production backup. The existing
   26-table ZIP workflow must not be used after this migration; use the new native
   encrypted backup or verified provider recovery. The synthetic restore is not
   evidence of recovery of the actual Supabase project.
3. In maintenance mode, within one transaction, apply `foundation_ddl()`, register
   the four requested companies, and assign every existing private-table record to
   its verified company. No default assignment or demo-record deletion is included.
   Then apply `runtime_ddl()`. Any unassigned row or pre-existing policy aborts the
   transaction. Preserve source counts and verify all composite constraints.
4. Create one dedicated non-privileged DB LOGIN for the existing Serkan account;
   apply `runtime_role_grants(role)`. Insert its account/role binding and exactly
   four read grants. Initially leave write grants false. No additional live users
   are requested by this release; the other test users are fictional.
5. Configure the existing explicit hashed login directory and signing secret, plus
   `CT_COMPANY_DB_CONNECTIONS_JSON` in server secrets, mapped by login name to its
   `role` and private `url`. Never expose these values in messages, logs or reports.
   Leave the old review flag unset; choose `CT_COMPANY_RUNTIME_MODE` as
   `SIGNED_ROLE_READ_ONLY`. Neither mode nor credentials are configured by this PR.
6. Validate sign-in and the four company views on iPhone/iPad/MacBook. After the
   separate write approval, enable the four explicit write grants and
   `SIGNED_ROLE_READ_WRITE`. Run one agreed business entry and verify dashboard,
   audit and recovery evidence. No live operation is authorized by a test pass.

## Operational limits / remaining acceptance

- The runtime intentionally enables only ADMIN writes and VIEWER reads. Department
  roles need an agreed narrower operation matrix before adding staff accounts.
- Lists currently return the most recent 100 records; paging/search is still needed
  for large historical lists. Supplier leads remain session results/JSON exports,
  not a durable supplier CRM. Live search provider availability is not certified.
- There is no outbound sales stock allocation/dispatch flow, statutory accounting,
  e-invoice, bank sync, customs submission, or automatic FX service in this release.
- Native backup exports ct_app only. Global login passwords, Supabase Auth/Storage,
  external files and secrets require separate protected recovery procedures.
- Native backup has an explicit CLI but offsite scheduling/retention is not activated.
  Configure the private backup environment, then run
  `python -m scripts.company_runtime_backup --output <new-encrypted-file.asctpg>`.
  Never use a regular RLS-limited application role as the backup operator.
- A concurrent write may be rejected by PostgreSQL serializable isolation; retry
  the unchanged request. Atomic rollback and the request ledger prevent duplicate
  committed operations. There is no automatic retry loop in the UI.

These are application capabilities prepared for deployment, not a claim that the
live four-company system has been migrated or is already production-approved.
