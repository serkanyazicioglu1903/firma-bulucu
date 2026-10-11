# AS Control Tower — Supabase security and backup readiness (11 October 2026)

These observations were gathered **read-only** from the connected project's
metadata. They are not a certification and do not automatically change grants,
RLS, pricing, passwords, or customer records.

## Verified state

- Supabase project **AS-CONTROL-TOWER**, PostgreSQL 17, Europe London
  (eu-west-2), active/healthy.
- Organization subscription: **Free**.
- The `ct_app` schema contains 26 business tables.
- **All 26 ct_app tables have RLS disabled.**
- Independent `pg_catalog` privilege checks show the `anon` and
  `authenticated` roles presently have neither schema USAGE nor direct
  table SELECT/INSERT/UPDATE grants on `ct_app`. This means the missing RLS
  is not, by itself, proof of public API exposure. It is nevertheless an
  important defense-in-depth deficit if roles/grants change later.
- At the time of inspection: 1 customer, 1 contact, 2 audit log rows;
  no product, purchase order, inventory lot or financial transaction entries.
- Supabase performance advisor reported missing foreign-key indexes
  (including `ct_app`). This should be addressed before large datasets or
  high concurrent load, not blindly as an unreviewed migration.

## Mandatory production decisions — not performed automatically

1. **RLS/grants:** Keep the `ct_app` schema outside public Data API exposure
   and do not add `anon`/`authenticated` grants. Design RLS policies for
   the intended access pattern before enabling RLS, even for private app
   tables. Do not run a mass `ENABLE ROW LEVEL SECURITY` migration without
   checking which database login owns the tables and how Streamlit authenticates.
   Current app users share a server-side PostgreSQL connection: Streamlit
   session roles are not independent PostgreSQL row-level identities.
2. **Managed backups:** Supabase documentation states that daily managed
   backups are provided on Pro, Team and Enterprise projects, not Free.
   Free projects should schedule secure off-site exports using Supabase CLI
   `db dump`, or deliberately upgrade the plan after an owner cost decision.
   The on-demand app ZIP export is NOT a substitute for encrypted managed
   backups or point-in-time recovery. A paid plan/upgrade has NOT been
   purchased or approved here.
3. **Real financial approval:** Test multiple users, bank reconciliation,
   stock reservations and restores before unrestricted production financial
   posting. Synthetic end-to-end PostgreSQL CI coverage is separate from
   real operational acceptance.
4. **Master onboarding:** Only approved actual master CSVs may be uploaded
   in an explicit, backed-up, ADMIN-only batch. No real company/ingredient
   entries were fabricated or inserted by this development work.

## Read-only sources and operator references

- Supabase RLS: https://supabase.com/docs/guides/database/postgres/row-level-security
- Supabase backups and Free plan note:
  https://supabase.com/docs/guides/platform/backups
- Supabase foreign-key index advisor:
  https://supabase.com/docs/guides/database/database-linter?lint=0001_unindexed_foreign_keys

No production SQL mutation has been run during this security inspection.
