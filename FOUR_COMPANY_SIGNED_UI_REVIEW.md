# Four-company signed read-only UI — disabled by default

This PR **connects the separate grant-aware PostgreSQL read adapter** to a
deliberately opt-in Streamlit review interface. It does **not** make the current
15 business tabs safe for multiple legal entities, and it does **not** migrate
or update any Supabase tables, record ownership, credentials or grants.

## Review mode behavior

Only after a separate approved installation sets the server-side secret
`CT_COMPANY_SCOPED_VIEW_MODE=REVIEW_ONLY_WITH_SIGNED_SESSION` will the Control
Tower business UI switch to a **restricted company viewer**. With that switch
active, all legacy Control Tower tabs (unscoped finance, CRM, imports, backups,
search, exports, reports, old dashboards and writes) are suppressed on the
Control Tower route; other independent app functionality requires its own
tenant/security audit before approval.

**Do not enable this flag on the live application yet.** Read access needs
a complete verified `ct_app.legal_entities` registry, non-null owner IDs in
all 8 critical tables, an approved `ct_app.company_read_grants` registry
and separately approved row and permission assignments. These do not exist
in the live database according to the last structural audit.

## Identity and access conditions

- Each user must be in explicitly configured `APP_USERS_JSON`, enabled, with
  a password-verified server login. The legacy single-admin password fallback
  does **not** grant company viewer access.
- A separate random secret `CT_COMPANY_SESSION_SIGNING_KEY` at least 32
  characters long is needed for a signed session HMAC. Signing only occurs
  after successful password authentication and is cleared on logout.
- During each read, the session HMAC, current enabled account and role are
  rechecked. An unsigned session or fake role does not provide data access.
- The username is used as a future principal ID after being derived from
  the signed server session. The **PostgreSQL grant** then requires an
  explicitly authorized matching legal entity, on every single SELECT.
- Selecting another company never adds access. No automatic ADMIN/Holding
  permissions or grand-total consolidation. The read-only viewer has a
  hard 100-row limit and no file export.

The signing key and database secrets **must never be placed in a PR or chat**.
Do not enable these keys or activate the mode until a backup/restore proof,
accountant-reviewed entity mappings, role audit, RLS or equivalent full route
audit, least privilege, transaction writes, and separate user go-live approval.

## Tests

Offline tests cover (1) signed/tampered and disabled-user sessions;
(2) access denied until click; (3) no selector for unsigned sessions;
(4) denied, schema-missing, and authorized fictional reads; and (5) exclusive
routing which excludes unscoped legacy screens. Real PostgreSQL synthetic
four-company grant tests from PR #57 remain required and run on each PR.

No live deployment, company authorization, feature flag activation or
migration is performed by merging this code alone.
