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

## Transactional PostgreSQL core (code-only, NOT enabled)

A new `scripts/postgres_operational_write.py` defines PostgreSQL `ct_app`
operations for authenticated, role-restricted customer/product creation, PO
creation, shipment planning and stock receipt, quality HOLD, AP invoice creation
and supplier settlement. These use parametrized SQL, row-level locks, a
single atomic PostgreSQL transaction per action, stock/amount checks, quality
payment guard and replay-reference checks. Every unexpected DB failure is
sanitized; tests use mocks, never the connected Supabase database.

**Server-side writes are OFF by default:** every operation returns
`disabled` unless `AS_CONTROL_TOWER_PG_WRITES_ENABLED=1` is explicitly set.
Do **not** enable this until real PostgreSQL integration tests, bank/quality
business-rule approval, multi-user permission audit, persistent backup/restore
and all remaining modules are migrated. No application UI calls these write
functions yet. There is no automatic dual-write, demo seed or backend switch.

## Real PostgreSQL Docker integration (isolated CI only)

A new GitHub Actions workflow starts a **fresh PostgreSQL 16 service** named
`ct_ci_control_tower` with fictional credentials. It builds the 26-table
`ct_app` schema and invokes the actual application operation functions:
customer/product creation, purchase order, shipment quantity checks, one-time
receipt, quality HOLD, quality case closure and stock release, AP invoices,
settlement, duplicate payment rejection across invoices, and account balances.
These integration tests use a disposable **GitHub runner localhost database**;
they do not connect to the user's Supabase project and cannot import company
records. The database is discarded when the CI job ends.

The production PostgreSQL code still demands TLS. A dedicated
`CT_LOCAL_POSTGRES_TEST=1` flag relaxes SSL *only* when the URI exactly
identifies loopback port 5432, test user `ct_ci`, test database
`ct_ci_control_tower`, and has **no URL query overrides**. Never configure
this CI flag on Streamlit or any internet-facing server.

CI acceptance is a better integration signal than mocked SQL tests alone, but
it is **not** a substitute for real Supabase access controls, backup/restore
drills, concurrent-user load tests, auditing, and mobile browser verification.
The operational write engine remains explicitly **disabled by default** and
is still not wired into the main Streamlit UI.

## PostgreSQL 360 operational read panel (ADMIN only)

A separate **🗄️ PostgreSQL 360** tab is now added to the existing Control Tower
navigation. This tab is **not a backend switch**. It uses audited, hard-coded
queries against the dedicated `ct_app` PostgreSQL schema to show up to 100
recent records per area: customers, product catalog, purchase orders, shipments,
inventory, quality, receivables, payables, bank/cash and financial transactions.
The main existing Control Tower and non-ADMIN role pages remain SQLite-backed.
No arbitrary SQL, demo data, dual-writes or PostgreSQL writes are allowed by the
new panel. Query attempts are on explicit user clicks only and require ADMIN
authentication; errors and credentials are sanitized.

The read queries are also exercised on a disposable PostgreSQL service in CI.
This is a **read-only acceptance milestone**. Before enabling any new
PostgreSQL write forms or real company data: verify role and row-level access,
backup/restore, audit, financial calculations, concurrency, and an intentional
full-application cutover plan.

## PostgreSQL master-data entry rollout (OFF by default)

The new optional PostgreSQL 360 forms support three master records:
`customers`, `product_catalog`, and `warehouses`. All form submissions
call the existing `ct_app` transactional writer with the ADMIN role from the
server session. A new **atomic audit-log insert** records the initiating actor,
role, operation, and table in the same PostgreSQL transaction; if writing the
audit record fails, the underlying business change is also rolled back.

**The forms and write engine remain disabled by default.** They are mounted
only when BOTH independent **server environment** settings are `1`:
`AS_CONTROL_TOWER_PG_UI_WRITES_ENABLED` and
`AS_CONTROL_TOWER_PG_WRITES_ENABLED`, and only for logged-in ADMINs. An
additional explicit per-form confirmation is required. The special local
PostgreSQL CI test mode cannot enable this Streamlit writer interface.
Do **not** set these variables on the connected Streamlit service until
security, backups, audit, multi-user and operational acceptance are complete.

The existing SQLite business screens still cannot see data written to
`ct_app`. These first PostgreSQL forms do not cover updates, deletes,
opportunities, quotations, stock allocations, invoice imports, accounts or
full financial reconciliation. A live feature-flag activation is a **separate
cutover decision**, not implied by merging this PR.

## Release blockers (do not skip)

1. Disposable PostgreSQL 16 CI integration now exercises the actual ct_app transactional code with fictional records. Still independently verify the user's Supabase deployment permissions, TLS, concurrency, and same-schema functionality before activating any writes.
2. Confirm persistent storage/backups. The default Control Tower uses a local SQLite file. To use a pre-mounted persistent disk, set `AS_CONTROL_TOWER_DB_PATH=/mount/persistent/as_control_tower.db` before startup; the target directory must already exist and be writable. A Streamlit cloud instance's ephemeral local filesystem is not an adequate durable production database. Changing the path does not migrate old data.
3. Perform manual phone and MacBook browser testing, including narrow viewport and authentication/role restrictions. Streamlit AppTest is not a physical device test.
4. Check real import duties, exchange rates, credit terms and margin calculations against approved sample invoices before financial decisions.
5. Validate product sourcing results manually against official manufacturer sites and commercial documents.
6. Verify authentication, secrets, backup/restore and concurrent write behavior with the target hosting configuration.
7. Obtain explicit owner approval before live backend activation, deployments involving new data flow, or writing production company data. (Earlier development PRs have already merged with owner approval.)

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
