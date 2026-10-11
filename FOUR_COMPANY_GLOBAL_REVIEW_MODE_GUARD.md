# AS Control Tower — global company-review mode isolation

## Problem

Until this change, `CT_COMPANY_SCOPED_VIEW_MODE` replaced the old business
tabs only inside the Control Tower route. The root `app.py` still rendered
the three main application tabs, including external sourcing/acquisition
widgets and their session-scoped exports. That is inconsistent with the
documented **exclusive** four-company review mode.

A misspelled or contradictory server-side mode setting previously returned
`False`, silently disabling the guard and exposing the original app route.

## Fix (off by default)

When the server mode is exactly
`REVIEW_ONLY_WITH_SIGNED_SESSION`, `app.py` now renders only the
already-existing signed, DB-grant-scoped PostgreSQL **read-only** viewer and
stops before loading the app's three main tabs. No legacy finance, CRM, role
portal, sourcing/acquisition, CSV export or unscoped controls are rendered.
Logout remains available. If the PostgreSQL connection is missing, the
review route fails closed.

An empty mode maintains existing behaviour unchanged. Unrecognized values,
non-string settings, or a disagreement between Streamlit Secrets and the
process environment block all legacy views. Direct Control Tower entry points
also reject invalid mode values and refuse a legacy SQLite fallback when the
signed PostgreSQL review flag is on.

## Scope of evidence and restrictions

Unit and Streamlit AppTest coverage checks a synthetically logged-in,
**unsigned** user; no legacy tabs, no export widgets, no false acceptance.
These tests DO NOT establish the identity of actual employees, company
registrations, real company grants, or the completeness of business record
ownership. Existing test-only RLS/transaction rehearsals remain separate.

**No flag is enabled by this PR.** No Supabase roles, RLS, schema, customers,
cash, stock, backup or access credentials are changed. Live four-company mode
still requires independently reviewed legal-entity assignments, company
permissions, full current backup **and independent restoration**, least
privilege DB roles, all 26-table tenant routes, financial reconciliation and
a separate explicit production go-live authorization.

Merging code alone is not approval to activate review mode or migrate data.
