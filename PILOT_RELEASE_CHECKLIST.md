# AS Control Tower — pilot release checklist

This is an **integration candidate**, not a production deployment.

## Implemented and exercised in CI

- Company acquisition search and manufacturer/supplier discovery are exposed in the Streamlit app.
- CRM, product/customer matching, quote and margin, purchasing, shipments, inventory, quality, receivables, payables, cash and management sections are present.
- Demo records are not inserted automatically. Fictional fixtures require `AS_CONTROL_TOWER_DEMO_SEED=1`.
- Empty product/warehouse workspaces show guidance rather than crashing on the affected forms. An isolated Streamlit smoke test also checks startup without fictional master data.
- Isolated SQLite tests exercise purchase order → shipment → inventory receipt → quality HOLD/release → supplier payment.
- Inventory receipts reject cancellation, excess quantity and repeated receipt.
- Payment/collection operations reject a repeated nonblank reference **within the same invoice**, and check amount and bank currency. Blank references have no replay protection.
- Separate offline fake-PostgreSQL staging tests cover procurement/stock/quality/payment guard and rollback logic.
- System Health offers a single explicitly confirmed PostgreSQL acceptance action: schema audit, rollback-only CRUD, and rollback-only fictional CRM/quote/purchase/stock/HOLD/finance workflow. The coordinator fails closed and does not reveal credentials. The action must be run in the target Streamlit environment; successful CI mocks **do not** prove connectivity to the user's Supabase instance.

## SQLite → PostgreSQL migration preparation

System Health now provides **SQLite → PostgreSQL geçiş ön kontrolü**, a read-only
check of the active SQLite file's integrity, foreign keys and expected 26-table
schema, plus PostgreSQL `ct_staging` row counts (no row contents). A successful
readiness result means the target **test schema is empty and eligible for an
explicit, separately approved staging import**, not that the app has changed
storage backends. Nonempty targets are blocked; no records are deleted.

The existing `scripts/staging_import.py` requires a consistent verified SQLite
snapshot + SHA256 manifest and a dedicated staging connection before it can
copy data. The imported data may include sensitive financial, customer and
audit records; do not perform an import unless staging access controls and a
retained source backup are verified. The active Streamlit application remains
SQLite-backed even after staging import, pending full backend replacement and
parallel/reconciliation acceptance.

## Dedicated future operational schema (not cut over)

`ct_staging` is a sandbox for fictional test records. Do **not** enter real
company records there. System Health now has an opt-in **ct_app** setup for a
separate, new, empty 26-table PostgreSQL schema. It checks the schema status
read-only and refuses to modify an existing ct_app. The optional create action
requires an explicit admin checkbox, is transactional, uses the checked-in
schema definitions, and never copies or deletes rows. It is not invoked
implicitly by app startup.

**Crucial:** All existing CRM, purchasing, inventory, quality, finance, audit,
reporting and security operations remain SQLite-backed. Creating ct_app does
not move any of those modules. Before real company data is entered, implement
and test authenticated PostgreSQL CRUD and transactional business rules for
**all** modules, migrate/reconcile any retained SQLite data, validate backup
and restore, and intentionally activate the fully reviewed backend. Avoid
silently running some modules against SQLite and others against PostgreSQL.

## First direct ct_app runtime read (still no cutover)

The ADMIN System Health panel includes **ct_app canlı tablo kayıt sayılarını oku**.
It opens a real read-only PostgreSQL transaction, validates the 26-table
`ct_app` structure first, and returns only aggregate row counts from 11
operational tables. This is intentionally the first observable application
query against the new durable database; it does not write, copy or expose
customer rows, or alter the existing SQLite business screens. Authentication
and the full transaction/write adapter must still be completed before any
real customer or finance data enters PostgreSQL via the main app.

## Release blockers (do not skip)

1. Validate real PostgreSQL schema and integration against an **isolated, non-production** database. The offline adapter test is not a live PostgreSQL test.
2. Confirm persistent storage/backups. The default Control Tower uses a local SQLite file. To use a pre-mounted persistent disk, set `AS_CONTROL_TOWER_DB_PATH=/mount/persistent/as_control_tower.db` before startup; the target directory must already exist and be writable. A Streamlit cloud instance's ephemeral local filesystem is not an adequate durable production database. Changing the path does not migrate old data.
3. Perform manual phone and MacBook browser testing, including narrow viewport and authentication/role restrictions. Streamlit AppTest is not a physical device test.
4. Check real import duties, exchange rates, credit terms and margin calculations against approved sample invoices before financial decisions.
5. Validate product sourcing results manually against official manufacturer sites and commercial documents.
6. Verify authentication, secrets, backup/restore and concurrent write behavior with the target hosting configuration.
7. Obtain explicit owner approval before merging PR #27, deploying or writing any production data.

## Safe review procedure

- Review draft PR #27, including changes brought in from PR #25 and PR #26.
- Run GitHub Actions on the PR head and confirm **both** checks pass.
- On an isolated machine or environment with dependencies installed, run:
  `python -m unittest discover -s tests -p 'test_control_tower_sqlite_integration.py' -v`
  `python -m unittest discover -s tests -p 'test_staging_ops_adapter.py' -v`
- Launch Streamlit only against an empty, disposable workspace during acceptance testing.
- Never point an unreviewed pilot at the production database.

## Known scope limit

The application UI's operational persistence remains SQLite-based. The staging PostgreSQL adapter is an isolated pilot, **not** a drop-in PostgreSQL backend for the entire app. The candidate should not be described as fully production-ready until the above release blockers are cleared.
