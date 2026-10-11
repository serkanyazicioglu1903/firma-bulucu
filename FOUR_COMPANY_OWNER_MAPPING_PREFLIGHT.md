# Four-company owner mapping preflight — human-reviewed, no migrations

This PR adds a **read-only, fail-closed source-data preflight** to the four
company project. It does not make assignments and does not collect the
user's actual records in GitHub or ChatGPT.

## What it reads

Only 8 fixed ct_app operational and finance tables:
purchase_orders, shipments, inventory_lots, quality_cases,
payables, receivables, finance_transactions and cash_accounts.

A PostgreSQL `REPEATABLE READ, READ ONLY` transaction returns fixed table
**row IDs, referenced parent IDs, and `md5(row_to_json(t)::text)` row hashes**.
Row data (customer names, invoices, addresses, amounts, bank details) are
not returned, logged, included in PRs, or rendered to a user.
Limits are 20,000 rows per table and 100,000 total. Larger sources fail
closed and require a separately designed streaming audit.

The code creates an ordered `sha256` snapshot fingerprint. Row hashes and
snapshot fingerprints detect data drift, **not authenticate a reviewer or
cryptographically secure sensitive database contents**. Restricted access to
the snapshot is still essential; no public upload/export should expose IDs.

## Explicit ownership plan contract

An independent verified finance/legal reviewer must supply a structured plan
with `source_sha256` and **exactly 8 allocation sets**. Each row requires:

- `record_id` matching a real existing source ID in its table;
- `company_code` from the four configured codes, **without guessing** from
  addresses, product names, warehouses, bank currencies or existing columns;
- `evidence_ref` referencing a separately stored reviewed legal/accounting
  document. No personal, customer, financial or supplier data in the ref.

The preflight rejects missing, unexpected or duplicate records, unknown
companies, missing evidence, stale source fingerprints, parent rows that are
not present and cross-company links for all 10 constrained relationships in
`OWNED_RELATIONSHIPS`. Every row is checked, including bank and finance
transactions, and the empty database cannot be certified.

The only passing status is `review_required`. It **never** returns
`approved`, does not set user grants or RLS policies, and has no code to
perform UPDATE/INSERT/ALTER or assign any owner.

## Disposable PostgreSQL rehearsal

CI uses fictitious A/B/C/D entities inserted inside a transaction which is
intentionally rolled back. The CI integration builds a synthetic manifest
from its deliberately known fake owner IDs **only in the test**, checks
full coverage, rejects missing allocations and stale source hashes, and
then verifies all its temporary columns/tables are absent after rollback.

**DO NOT generate real ownership mappings from existing owner columns or
names.** The production database does not have a verified 4-company mapping.

## Backup and production readiness

An existing rollback-only disposable PostgreSQL backup restore drill
(`postgres_restore_drill.py`) tests the 26-table ZIP format and FK/row
roundtrip. Passing this CI drill **is not proof of a restored real current
Supabase backup, recovery point objective, offsite retention, permissions
or independent disaster-recovery restoration**. These remain go-live gates.

Other outstanding blockers: verified legal entity registration and tax IDs;
manual allocation and approval, *every* 26-table access path and shared CRM
ownership, RLS/server grants, bank and stock reconciliation, signed manifests,
composite FKs, a REAL recent encrypted backup and independent restore,
consolidation/eliminations, concurrency test, Mac/iPhone acceptance, and
explicit user approval for the scoped production migration.

**No production Supabase changes, no feature toggles, no real-data transfers,
no PR auto-merge.**
