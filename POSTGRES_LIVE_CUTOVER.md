# AS Control Tower — PostgreSQL live cutover

## Activation behavior

The Streamlit deployment already has `DATABASE_URL` in Secrets. Once this
reviewed change is merged and the deployment restarts, Control Tower selects
the persistent **Supabase PostgreSQL `ct_app` schema by default**. Both the
business forms and their dashboards/reporting/AI reads use PostgreSQL through
the compatibility layer. Manufacturing/producer sourcing and company-acquisition
search remain separate from the business database.

There is **no automatic table creation, destructive migration, mock data seed,
or data copying**. The local SQLite file is preserved untouched. The cutover
refuses to proceed when:

- The `DATABASE_URL` secret is invalid or Supabase is unreachable;
- The full `ct_app` 26-table structure is not valid;
- Any retained legacy SQLite business record is detected; or
- The old SQLite file's schema or integrity cannot be verified.

If PostgreSQL fails, Control Tower displays a safe error and **does not fall
back to SQLite**, preventing silent split-brain records.

## Implemented safeguards

- Psycopg connection pool with mandatory TLS (unless an exact disposable local
  CI test URL), bounded connections, statement timeouts and disabled server-side
  prepared statements for transaction-pooler compatibility.
- Existing 26-table Control Tower business forms, user role portal, AI and
  management reporting resolve to the same `ct_app` backend.
- A known-syntax SQLite-to-PostgreSQL SQL compatibility shim preserves bound
  parameters, aliases, date arithmetic, min/max and rounding behavior.
- Direct form writes require authenticated role permissions and produce an
  atomic PostgreSQL audit entry inside the same transaction.
- Shipment stock receipt, supplier payments and customer collections use the
  audited native PostgreSQL transaction engine with replay guards, row locks,
  currency consistency and quality HOLD payment blocking.
- Empty workspace and detailed PostgreSQL Streamlit integration tests run on
  a **disposable localhost PostgreSQL 16 database only**; they never access the
  user's Supabase instance.
- Admin-only **Sistem Yönetimi** contains live health, audit and optional
  on-demand ZIP export of all 26 PostgreSQL tables. The archive contains
  sensitive company data and is intentionally not stored by this application.

## First live acceptance on phone and Mac

1. Reopen or reboot the existing Streamlit app after merging.
2. Log in to AS Control Tower. At its top expect:
   **🟢 Canlı veri modu: ... Supabase PostgreSQL ct_app**.
3. Check the executive panel shows empty new business data, not demo rows.
4. In **Sistem → Sistem Sağlığı**, run count checks.
5. Add one explicitly approved *real* nonfinancial master entry (e.g. a
   company-own warehouse or test-labeled record) and confirm that it persists
   after reboot. Do not use fictional production invoices.
6. Verify role restrictions and export a verified backup before entering
   substantial financial records. Confirm provider-managed encrypted backup
   and restore policy separately.

## Critical limitations and rollback

- The GitHub CI test verifies the code against PostgreSQL 16 but **does not
  constitute a live Supabase write, production load, backup-restore, or device
  acceptance test**.
- There is no automatic import of historical SQLite data. The owner's
  last read-only preflight showed 0 business rows and an empty `ct_app`
  schema. Live startup repeats the SQLite-data gate rather than trusting the
  prior screenshot.
- Provider-managed Supabase snapshots, restore drills, connection permission
  hardening, row-level security and multi-user concurrent load testing are
  operational prerequisites for unrestricted financial production use.
- The local SQLite file remains available for investigation but should not
  become an independent live source after cutover. If Supabase is unavailable,
  leave the app stopped/fail-closed and repair or restore the database; do not
  resume new business writes to ephemeral SQLite.

## Development status

This branch intentionally replaces the old **SQLite pilot default** only when
the trusted `DATABASE_URL` is configured and validated. Without a configured
PostgreSQL connection, existing isolated SQLite development/test behavior is
left unchanged. Legacy SQLite-dependent System Management is replaced by the
PostgreSQL-only administration panel while PostgreSQL is active.
