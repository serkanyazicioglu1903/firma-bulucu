# Legal-entity separation: disposable rehearsal only

**Status: proposed, not production approved.** This branch adds a two-phase,
fixed-table PostgreSQL DDL plan and an isolated CI rehearsal. No migration
is executed by the application; no Supabase schema, rows, grants or secrets
are changed.

## Phase A — reversible *schema rehearsal*

`scripts.postgres_legal_entity_rehearsal.additive_ddl()` builds SQL to:

- Introduce an empty legal-entity registry with no real or dummy companies.
- Add a **nullable** `legal_entity_id` and owner lookup index to each of
  eight critical business tables (PO, shipment, lot, quality case, payable,
  receivable, finance movement, bank/cash account).
- **Never backfill**, infer or assign owner to a legacy record.

A nullable column is an unsafe intermediate state for real business posting.
Application reads, writes, CSV exports, billing and reports MUST remain
blocked for multi-company production until both phases and access controls
are validated.

## Phase B — preconditioned enforcement only

`enforcement_ddl()` builds SQL to:

- Require a non-null owner on all eight tables; fails when an ownership
  assignment is missing.
- Enforce ten composite foreign-key relationships that include company ID
  (for example, the shipment and its purchase order must have the same owner).
- Avoid cross-company payment links between bank accounts, receivables and
  payables.

Shared customer/product master records are not yet separated; additional
entity-aware authorizations and scoped read queries are mandatory. Schema
enforcement **does not by itself provide row-level access controls**.

## Actual CI acceptance and limits

The disposable PostgreSQL test inserts TWO **synthetic** companies,
assigns existing *synthetic CI* rows inside a single transaction, applies
both phases, proves a valid same-company shipment is accepted, a
cross-company shipment is rejected, and an ownerless bank entry is rejected.
It **rolls back all temporary DDL and records** before other tests.

DO NOT copy this CI backfill into production. Real ownership must be
reconciled with finance and operations before any changes.

Still needed for live use: signed entity/legal-name master, accountant-approved
opening balances, transaction and financial report scoping, least-privilege
per-user access, backup and isolated restore, a rehearsed rollback,
and a separate explicit authorization to run a production migration.
