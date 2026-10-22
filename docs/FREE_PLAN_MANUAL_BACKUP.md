# Free-plan manual database backup — AS Control Tower

This procedure does not upgrade Supabase, change the live schema, or export any passwords to GitHub.

1. On a **trusted operator computer** with PostgreSQL 17 client tools, configure `PGHOST`, `PGPORT`, `PGDATABASE`, `PGUSER`, `PGPASSWORD`, and `PGSSLMODE=require` privately. Obtain values from Supabase's **Connect** dialog. **Never paste credentials into chat, GitHub issues, logs or screenshots.**
2. Create a private encrypted backup folder, inaccessible to other users, and run:
   ```bash
   python -m scripts.manual_ct_app_backup --output /private/backup/as-control-tower-ct-app.dump
   ```
3. Preserve the reported SHA-256 digest and archive in encrypted offsite storage. This backs up the `ct_app` schema and its rows, **not** the entire Supabase project (auth, other schemas, storage, custom roles and settings are excluded).
4. The command only checks that `pg_restore --list` can read the archive. **That is not a restore test.** Create a separate, empty, isolated PostgreSQL 17 test database, then restore there using a trusted operator account:
   ```bash
   pg_restore --exit-on-error --no-owner --no-acl --dbname=ct_restore_test /private/backup/as-control-tower-ct-app.dump
   ```
   This example is safe **only** if `ct_restore_test` is a separate disposable database and connection environment points at the test server. Never execute it with production connection settings.
5. In the restored database verify 26 tables and reconcile original counts: `customers=1`, `contacts=1`, `audit_log=2`, all remaining 23 tables empty. Verify application schema, constraints, and data access.
6. Only after independent restore verification, approve and rehearse four-company ownership, dedicated database roles, and forced RLS in isolation. A successful dump or green CI **never** authorizes production cutover.

The backup script intentionally fails closed when the destination exists or credentials/TLS are missing. It does not execute a restore, grant rights, seed company records, or enable company mode.
