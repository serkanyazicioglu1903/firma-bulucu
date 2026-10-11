# AS Control Tower — ADMIN 26-table read-only ownership panel

**Review-only. No live database or permission changes, user assignments,
real exports, backup replacement, schema migration, or activation.**

The existing `scripts/postgres_company_full_coverage.py` review is now
available to a logged-in ADMIN in the Control Tower screen, next to the
separate Supabase API/RLS privilege review.

## Behavior

- Control is displayed only to ADMIN users.
- No DB connection occurs until the administrator explicitly clicks the
  `26 tablonun şirket ayrımı eksiklerini denetle` button.
- One read-only, repeatable-read PostgreSQL metadata transaction reads the
  pg_catalog table inventory. No customer names, bank balances, invoices,
  product prices, business rows, credentials or real row owner mappings are
  fetched or exported.
- Shows **26/26** table coverage, enabled RLS flags, presence/non-null
  constraints of required legal-entity owner columns (8 tables), and the
  remaining 18 tables that need legal/accounting visibility design.
- If any metadata is missing or malformed, the panel fails closed. An
  all-green structural result still displays **ONAYLI DEĞİL**.
- Displays no company selector that could impersonate company permissions.

## Verification

- Unit tests: unauthorized users do not see the panel; no auto-query;
  disabled DB; incomplete schema; 26 RLS and 8 owner columns remain
  insufficient for production approval.
- Dedicated disposable real PostgreSQL integration tests check that the
  current synthetic legacy schema is flagged as incomplete and is not
  modified by the metadata call.
- GitHub CI is triggered by future modifications to this panel or its tests.

## Still blocked

This interface is a diagnostic, **not a four-company rollout**. Production
cutover requires independently verified legal entity registration, named
user-to-company grants, ownership mapping for all linked records, isolated
transactional writes, least-privilege DB role architecture, RLS or equivalent
secure access controls across every API/report/export route, and an
independently restored encrypted backup with reconciled record totals.

In particular, the current 26-table export is not a complete group-company
backup after registry/grant tables have been introduced. Never rely solely
on a generated ZIP's checksum as disaster-recovery proof.

Current Supabase data, policies, settings, credentials and backups are
unchanged by this PR. Merging code alone does not authorize those changes.
