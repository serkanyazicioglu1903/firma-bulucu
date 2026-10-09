# AS Control Tower — PostgreSQL staging migration

Status: OFFLINE SCHEMA GENERATOR ADDED. Do not enable PostgreSQL as the business database in production.

Run `python scripts/build_pg_schema.py --output postgres_staging_schema.sql` to generate reviewable staging DDL locally; this command never connects to Supabase. Run `python -m unittest tests.test_postgres_staging_schema -v` for offline regression checks. The output is not automatically applied.

## Current architecture (verified against main)
- `control_tower.py` opens SQLite directly and defines ~24 operational tables.
- `security_admin.py` has separate SQLite security/audit tables and backup routines.
- `ai_manager.py`, `management_reports.py`, and `role_portal.py` each open SQLite independently.
- Existing PostgreSQL diagnostic runs only `SELECT 1` via `DATABASE_URL`. Successful connectivity does **not** mean the business app uses PostgreSQL.
- SQLite-specific constructs include `AUTOINCREMENT`, `PRAGMA`, `INSERT OR ...`, `date('now')`, `julianday`, and positional `?` placeholders. These require compatibility changes.

## Staging implementation sequence
1. **Credentials and isolation:** Keep `DATABASE_URL` in Streamlit Secrets. Use a distinct staging PostgreSQL database/schema and least-privileged app credentials. Do not print connection URIs or errors containing secrets.
2. **Schema:** Define versioned PostgreSQL migrations for operational + security/audit tables; convert integer primary keys to PostgreSQL identities, preserve foreign keys and unique constraints, and review monetary precision. Avoid exposing application tables through a public API.
3. **Data layer:** Introduce one database adapter and route all reads/writes through it, including management reports, role portal, AI manager, audit and backup. Use parameterized SQL and transactional writes.
4. **SQL parity:** Replace SQLite-only date expressions, upsert syntax, schema introspection, ID retrieval, and transaction semantics. Validate role permissions before writes.
5. **Safe test dataset:** Seed fictional data in staging only. Verify create/update/delete, cross-table referential integrity, partial stock receipts, quality HOLD, invoices/settlements, and currency-aware calculations.
6. **Backups:** Export and verify SQLite snapshot before any migration. Create a documented PostgreSQL backup/restore procedure and test a restore in staging. Do not assume the free plan includes production-grade backups.
7. **Cutover:** Only after green CI and staging smoke tests, choose an explicit cutover window. Export/import approved data, reconcile per-table counts and totals, switch with a feature flag, monitor, and keep a rollback path.
8. **Production:** Confirm authentication/authorization, connection pooling, encryption, backup policy, access logging, and recovery procedure before entering actual customer/financial records.

## Acceptance criteria
- PostgreSQL tests pass with no access to production credentials in CI.
- No write is issued during connectivity tests.
- Existing SQLite mode and regression suite remain functional until cutover.
- Staging data survives app restart/redeploy.
- Every operational and security screen uses the same backend.
- Per-table record counts, stock quantities, currency totals and audit records reconcile.
- A rollback restores service without silent data loss.

## Explicit non-goals for this branch
- No live Supabase DDL or data modifications.
- No automatic production cutover.
- No real business data migration or secrets committed to GitHub.

## Stage 1: verified backup preflight (added 2026-10-08)
- Supabase SQL Editor successfully wrote and read a single test record in `ct_staging.migration_check`. This proves only that manual PostgreSQL access works, **not** that the Streamlit application has switched databases.
- The live Streamlit application still uses SQLite. Its hosted `as_control_tower.db` is not automatically accessible from this repository or this script. Do not mistake a local demo SQLite file for the actual live data.
- On a trusted machine with the **actual source SQLite file**, create a private backup directory and run:
  `python scripts/backup_sqlite.py --source /path/to/actual/as_control_tower.db --dest /private/backups/ct-YYYYMMDD.sqlite3`
- Keep the `.sqlite3` and `.sqlite3.json` manifest off GitHub; check manifest SHA256 and row counts before importing anything. Backup alone does not make Streamlit Community Cloud SQLite durable.
- The old `migrate_sqlite_to_postgres.py` importer is intentionally disabled: it used `if_exists='replace'`, which can destroy existing tables and constraints.
- Next implementation: reviewed, repeatable, staging-only PostgreSQL importer, FK/identity handling, and full record reconciliation. **Do not run an importer or switch the production app yet.**
- Rotate any database or app passwords exposed in screenshots; update Streamlit Secrets with the new values. Never share connection strings with passwords in screenshots.
- Product catalog import from `planetgida.com.tr` and `asgidakimyasallari.com` is deferred until staging migration and product master deduplication are complete.

## Stage 2: empty test tables created (2026-10-09)
- The application reported **27 tables in `ct_staging`**, including the 26 expected application table names and the existing `migration_check` table. This is verified through the administrator's read-only UI inspection; it does not establish column or foreign-key correctness.
- The business application still uses SQLite. The 18 demo records must **not** be imported into PostgreSQL as real company data.
- This change adds **Tablo yapısı ve ilişkileri doğrula** under System Health: read-only checking of each expected column name, mapped type, nullability, identity status, PK, unique and FK metadata. No business table rows or passwords are read.
- Before any cutover, run this check against Supabase and resolve discrepancies; then test transactions and business workflows separately.

## Stage 3: structural check passed; rollback-only CRUD smoke test prepared (2026-10-09)
- The administrator's **read-only** Supabase validator returned success for the 26 expected table schemas, including nullability, types, primary/unique and foreign key constraints. This is not evidence that Streamlit business modules work with PostgreSQL yet.
- The new opt-in **PostgreSQL işlem testleri (geri alınır)** control uses only `ct_staging` with fictional synthetic rows. It exercises customer/product/quote joins, task insert-update-delete, purchase order/shipment/warehouse/inventory joins, quality, receivables and payables.
- All test writes run in a **single forced-rollback transaction**, with explicit negative IDs to avoid consuming identity sequences. It verifies its test IDs no longer exist afterward.
- This is a technical database CRUD smoke test, **not** a production backend switch, full business-rule test, or import of real/demo company data.
- Run only after explicit administrator confirmation in the System Health UI. The current SQLite-backed production app remains unchanged.

## Stage 3: rollback-only synthetic PostgreSQL workflow smoke test (2026-10-09)
- The administrator confirmed 26 expected ct_staging application tables pass read-only column, nullability, identity, PK, UNIQUE and FK metadata validation.
- A new **explicit, separately confirmed** System Health action can exercise temporary fictional rows across CRM, product, quote, task, purchasing, shipment, inventory, quality, receivables, and payables.
- The test uses a single PostgreSQL transaction and **forces ROLLBACK on success or failure**, then queries that the temporary IDs are absent. It does not import the 18 SQLite demo records or alter the active application backend.
- Pending: run this test using the app, inspect the result, implement the shared PostgreSQL data adapter for the normal UI, and validate restart persistence and a backup/restore procedure before cutover.
