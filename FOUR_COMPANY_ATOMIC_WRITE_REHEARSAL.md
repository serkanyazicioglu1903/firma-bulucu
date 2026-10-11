# PR #60 — Four-company atomic write safety rehearsal

**Status: not deployed, not activated, CI database ONLY.**

The earlier PRs (#55–#59) prepared four-company display labels, synthetic
ownership and composite-FK tests, grant-controlled read-only access, and
currency-separated financial overviews. They did **not** provide a safe
four-company transaction writer.

This change adds `scripts/postgres_scoped_company_write_rehearsal.py`,
a **separate** test-only transaction engine. It handles three limited flows
without changing any existing application data or production code path:

1. **Purchase orders:** create only with an exact, active legal entity;
   verified write grant, server-validated principal, company-associated depot;
   valid globally shared product master; positive quantity and unit price.
2. **Shipments:** lock its parent PO; allow only matching company, warehouse
   mapping and ordered quantity. Prevent duplicate shipments/overbooking.
3. **Payable invoices:** accept only the same company's PO and supplier;
   require matching currency, date and amount; block duplicate invoices.

Every insert stamps `legal_entity_id`. Every successful operation inserts an
entry into an **entity-scoped immutable-by-design audit table within the same
transaction**, so an audit failure rolls back the business write.

## Database guard

The code requires all eight critical tables to have non-null owner IDs, a
verified active company row, and matching explicit PostgreSQL grants:

- `company_read_grants.can_read=TRUE`
- `company_write_grants.can_write=TRUE` (default **FALSE**)

Both grants and the legal-entity row are locked against concurrent revocation
until commit, so a read-only staff role, an ADMIN label, a company selector,
or access to the holding **never** implies write permission. Existing
warehouse rows require an explicit `company_warehouse_scope` association.

The three proposed extra tables are returned as reviewable **offline SQL
text only**; the program does not execute migrations on startup. The
review SQL has no inserted user grants, no hardcoded real IDs and no company
record assignment.

## Non-bypassable CI target restriction

The public rehearsal wrapper only runs when ALL of the following match:
`CT_LOCAL_POSTGRES_TEST=1`, `AS_CONTROL_TOWER_PG_WRITES_ENABLED=1`,
`CT_TEST_DATABASE_URL` matches the argument exactly, loopback IPv4/localhost
port 5432, CI-only username/database, and disabled SSL restricted to the
local ephemeral Docker test. A real Supabase hostname is **always refused**.

The inner cursor functions are for the isolated disposable integration test;
they are not external APIs or production entry points.

### What gets checked by CI

- Four fictional A/B/C/D entities created **inside an intentionally rolled
  back transaction**; no actual AS company names/IDs copied into tables.
- An account may write only to explicitly granted A and D; B and C denied.
- Wrong-company shipments/invoices/depot assignments denied.
- Role mismatch denied; write-grant revocation blocks further writes.
- Correct purchase → shipment → payable inserts match company owner IDs.
- Audit entries exist for each successful operation and none for denied ones.
- All temporary tables, records and owner columns are rolled back before the
  test finishes.

## Explicitly NOT delivered yet

- Real production DDL, verified company IDs, bank permissions and data backfill
- Automatic backups and successfully **restored** offsite snapshots
- Production role account management, RLS, full application/legacy SQL scope
- Company-scoped warehouse receipts, stock updates, QA release/hold, payments,
  collections, payment reference reconciliation, imports or exports
- Approved tenant consolidation, intercompany eliminations, FX conversion
- Any change to the live Streamlit feature flags, secrets or permissions

Never merge or deploy as a claim of multi-company go-live. Follow the approved
backup, company-mapping and rollback plan before any production mutation.
