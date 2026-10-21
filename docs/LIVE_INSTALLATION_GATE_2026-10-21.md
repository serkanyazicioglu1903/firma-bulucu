# AS Control Tower — live installation gate (21 October 2026)

**Status: BLOCKED FOR FOUR-COMPANY CUTOVER.** This is an installation checkpoint, not a successful deployment.

## Verified production state
- Supabase project: `weunzozedjymwsgwsohi` (AS-CONTROL-TOWER, eu-west-2), ACTIVE_HEALTHY.
- Application schema: `ct_app`, 26 existing tables.
- All 26 tables: RLS disabled, FORCE RLS disabled, zero policies, no `legal_entity_id`.
- Exact baseline: `customers=1`, `contacts=1`, `audit_log=2`; all other 23 tables have zero rows. **Total = 4 rows**.
- Last read-only metadata check: 2026-10-21. No schema changes were performed.
- GitHub PR #95 merged after successful offline CI. CI success is **not** live security verification.

## Hard release blockers
1. Independently verified **restorable** database backup and documented restore test.
2. Explicit owner-approved company mapping for existing customer/contact records; audit records remain internal.
3. Rehearsal on an isolated disposable Postgres environment, including full rollback.
4. Per-company authenticated least-privilege database roles and verified forced RLS on each private table.
5. Decisions on product catalog, system settings and audit log visibility; no automatic global sharing.
6. End-to-end test: CRM → quote → purchase → shipment → inventory → receivable, including negative cross-company access tests.
7. Explicit authorization for production schema migration and runtime cutover.

## Operator sequence
1. Verify a restorable backup. **Do not infer restore ability from a green health check.**
2. Export row-count baseline and record a hash of the approved migration manifest; never export customer PII into CI logs.
3. Rehearse `scripts/four_company_foundation_ddl.py` only inside a disposable database with rollback. This module is a plan, **not** an executable production migration.
4. Reconcile all four existing rows, approve ownership and security decisions, and validate least-privilege roles.
5. Schedule coordinated maintenance and disable legacy unscoped write paths before changing production ownership columns.
6. Apply reviewed migrations only after owner approval, verify all policies and negative cross-company tests, and reconcile the four original rows.
7. Enable the company runtime only after all release gates pass. Keep a tested rollback path.

**Never** enable forced RLS or add ownership columns on the current production schema in isolation: the legacy app is not company-scoped and may become unavailable. No default company assignment is safe.
