# AS Control Tower — backup source checks and encrypted restore rehearsal

**Preparation only. Does not verify, restore, read or modify the user's actual
Supabase database. Does not enable four-company production.**

## Mobile / Mac verification

On an authenticated ADMIN backup download, the existing legacy 26-table
ZIP export and AES-256-GCM .asct export now show the SHA-256 of the **actual
downloaded bytes being offered**. Copy this SHA-256 reference to a separate,
trustworthy location before relying on the archive (e.g., a password manager
entry kept distinct from the backup). Do not store passphrases in tickets,
GitHub or in the ZIP.

The verification screen accepts an optional **independently saved** 64-hex
SHA-256 reference. If supplied, a mismatched or malformed reference rejects
the upload BEFORE the ZIP or AES inner check shows success. A matching
reference only confirms the bytes match the separately recorded reference;
it does **not** certify the reference's authenticity, archive provenance,
or actual restore. If absent, the screen warns that reference verification
has **not** occurred. It does not claim a successful disaster recovery test.

A SHA-256 derived from the *newly uploaded file itself* and pasted alongside
that same file would be a meaningless origin check. The reference must
come from a separate trusted earlier export event.

## Complete encrypted restore flow in disposable CI

A new function `verify_disposable_encrypted_restore` enforces the existing
strict local Docker PostgreSQL destination guard **before decryption**,
then runs authenticated AES decrypt -> 26-table ZIP allowlist/checksums ->
PostgreSQL transactional restore with all constraints and row reconciliation
-> **mandatory rollback**. It returns table/row counts only; no data values.

This is now tested with a fully synthetic PostgreSQL export encrypted in
memory. The disposable schema is absent again after success. Production
destinations are rejected, and a wrong passphrase blocks restoration.

## Important limitation

The old legacy ZIP still contains only the original 26 application tables.
If company registry, access grant and other new tables exist, that ZIP is
intentionally blocked as a **complete** backup. The SHA feature changes
nothing about that limitation.

The independent restore of an up-to-date **full Supabase backup**, including
roles, security settings, schema, four-company ownership, all data and
access grants, has **NOT** been done. The Supabase provider backup retention
and point-in-time-recovery configuration remain unverified.

Required for real cutover: independently verified full backup and recovery
in a separate authorized environment, rollback plan, record count checks,
approved company identity + user access mappings, least privilege/RLS across
all routes, and explicit separate approval. The production database,
permissions, Secrets and feature flags are untouched by this PR.
