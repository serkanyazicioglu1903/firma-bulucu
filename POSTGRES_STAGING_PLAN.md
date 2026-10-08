# AS Control Tower — PostgreSQL staging migration

Status: OFFLINE SCHEMA GENERATOR ADDED. Do not enable PostgreSQL as the business database in production.\n\nRun `python scripts/build_pg_schema.py --output postgres_staging_schema.sql` to generate reviewable staging DDL locally; this command never connects to Supabase. Run `python -m unittest tests.test_postgres_staging_schema -v` for offline regression checks. The output is not automatically applied.

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
