"""Manual PostgreSQL backup for ct_app. No production restore or migration.

Requires pg_dump/pg_restore and libpq PGHOST, PGPORT, PGUSER, PGPASSWORD,
PGDATABASE environment variables supplied privately by the operator.
Never put passwords in CLI arguments, logs or committed files.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys

SCHEMA = "ct_app"


def backup_commands(destination):
    """Only one fixed schema, custom format, and a local archive validation."""
    return (
        ["pg_dump", "--format=custom", "--schema=" + SCHEMA,
         "--no-owner", "--no-acl", "--file=" + str(destination)],
        ["pg_restore", "--list", str(destination)],
    )


def validate_environment(env):
    """Reject missing connection details and disabled TLS for remote hosts."""
    required = ("PGHOST", "PGDATABASE", "PGUSER", "PGPASSWORD")
    if any(not env.get(k) for k in required):
        return False
    if env.get("PGHOST") not in ("localhost", "127.0.0.1"):
        return env.get("PGSSLMODE") in ("require", "verify-ca", "verify-full")
    return True


def create_archive(destination, env=None):
    env = dict(os.environ if env is None else env)
    if not validate_environment(env):
        raise ValueError("postgres_connection_configuration_required")
    target = Path(destination).expanduser().resolve()
    if target.exists():
        raise ValueError("backup_destination_already_exists")
    if not target.parent.is_dir():
        raise ValueError("backup_destination_directory_missing")
    dump, check = backup_commands(target)
    try:
        subprocess.run(dump, env=env, check=True, capture_output=True)
        if not target.is_file() or target.stat().st_size == 0:
            raise RuntimeError("empty_backup")
        listing = subprocess.run(check, env=env, check=True,
                                 capture_output=True, text=True).stdout
        if "ct_app" not in listing:
            raise RuntimeError("ct_app_not_in_archive")
        digest = hashlib.sha256(target.read_bytes()).hexdigest()
        return {
            "archive": str(target),
            "bytes": target.stat().st_size,
            "sha256": digest,
            "archive_list_verified": True,
            "restore_verified": False,
            "production_migration_approved": False,
        }
    except Exception:
        # A partial archive is never acceptable as a backup.
        target.unlink(missing_ok=True)
        raise


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True)
    args = parser.parse_args(argv)
    try:
        result = create_archive(args.output)
    except (ValueError, RuntimeError, OSError, subprocess.CalledProcessError):
        print("backup_failed: inspect private operator logs", file=sys.stderr)
        return 1
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
