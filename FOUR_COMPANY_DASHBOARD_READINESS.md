# AS Control Tower — Four-company readiness overview (read-only)

**Purpose:** phone-visible ADMIN dashboard for the owner-confirmed four
incorporated business entities, without misrepresenting the current
single-schema accounting data as tenant-isolated.

- AS İleri Gıda
- Planet Ingredients
- AS Food Global Ltd
- AS İleri Holding A.Ş.

These are **display labels only** until full legal registration names, tax
identifiers and mappings to actual PostgreSQL entity IDs are reviewed.
No full legal company records are inserted by this PR.

## What is available

1. **🏢 Grup Şirketleri — 4 şirket / canlı ayrım kontrolü** appears
   directly above the large Streamlit tab bar, reachable on an iPhone.
   It lists four labels with explicit *not verified* status.
2. The administrator can click to run a **read-only structural metadata**
   check for direct ownership columns in eight operation/finance tables.
   It never retrieves customer or bank rows, and never performs company
   switching, permissions grants or data writes.
3. The existing **Canlı kullanım kabul raporu** now explicitly reports
   four companies, continuing to block live sign-off until isolation is
   independently verified.
4. Offline role tests, metadata tests and disposable PostgreSQL mobile
   UI smoke checks are added. No production database schema is modified.

## What is NOT implemented

- Per-company company IDs in production ct_app
- Full real legal-entity matching, bank and inventory ownership backfill
- Authenticated per-entity user grants for normal transaction screens
- Company-scoped CRM, inventory, payments, financial and dashboard queries
- Intercompany reconciliation, multi-currency eliminations and consolidated P&L
- Actual automated encrypted offsite backup, restoration proof and sign-off

**WARNING:** Until these exist, the existing financial/stock tabs do not
become multi-company-safe merely by showing a four-company overview.
Do not import mixed-company data. A user grant shown in a mocked test
is NOT a grant from a real authenticated production user.

Any migration, existing record assignment or live permissions changes
require a separately approved and verifiably restorable backup.
