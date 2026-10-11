# AS Control Tower — review of four-company user access

**Status: offline preparation only. No live users or permissions assigned.**

## Signed session security

The optional company-scoped review mode now requires a configured
APP_USERS_JSON account with a nonempty, salted
`pbkdf2_sha256` password hash (at least 200,000 rounds), in addition to
the separate server-side signing secret, enabled role and password-verified
login. A plain-text account or legacy single-admin password can still use
existing legacy functionality but **cannot gain signed company scope**.

The HMAC now binds the session to the **server-registry password hash**,
username, role and session ID. Changing the registry password hash revokes
previous company signatures immediately on the next protected read;
disablement and role changes also deny access. Users must authenticate again
to get a fresh company signature after a password change. Existing signed
sessions use the earlier signature format and will similarly require
re-login after this code version is deployed.

Neither signing secrets, credential hashes nor actual usernames are placed
in this PR. No sign-in settings or secrets are changed automatically.

## Offline grant plan contract

`scripts/company_access_manifest_review.py` validates a human-reviewed
plan without talking to PostgreSQL, Streamlit or production accounts.
Inputs are a sanitized account registry and a separate proposed plan.
Every account, including disabled accounts and those explicitly assigned
**zero** companies, needs exactly one evidence-backed decision.

Every proposed company read/write must name exactly one of the four fixed
internal company codes, specify literal boolean values and include an
individual evidence reference. A write always requires read. Disabled accounts,
duplicate users, missing decisions, duplicate/wildcard companies, stale
account snapshots, invented roles, unsupported write roles and malformed
evidence all fail closed.

ADMIN is **not** automatically granted all four companies. AS İleri Holding
is **not** implicitly granted subsidiaries. The validator outputs only
structural status, aggregate counts and fixed issue codes, not usernames,
business data, or personal access mappings.

`registry_fingerprint()` ignores password hashes and plaintext secrets,
and detects changes in username, role or enablement. Its SHA256 is only a
drift indicator, **not** a cryptographic signature, accountant approval or
evidence that an identity is real.

The only passing result is `review_required`; it never says access was
granted or production cutover approved. This feature does not write to
company_read_grants, company_write_grants, APP_USERS_JSON or Supabase and
cannot enable live flags.

## Remaining live blockers

Legal registry identifiers and company IDs must be independently verified;
all relevant 26-table record ownership and customer/warehouse/bank data
relationships need explicit review; signed login must be tested with
genuine accounts and production least-privilege DB roles. Full current
backups **must be restored to an isolated environment** and reconciled.
No live financial data, role policy or migration may change without an
additional explicit go-live decision.
