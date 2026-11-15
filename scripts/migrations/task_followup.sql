BEGIN;
SET LOCAL lock_timeout = '3s';
ALTER TABLE ct_app.tasks ADD COLUMN IF NOT EXISTS followup_details TEXT;
COMMIT;
