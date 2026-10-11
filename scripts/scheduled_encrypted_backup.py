"""Opt-in, encrypted, READ-ONLY operational backup for GitHub Actions.

Never use this module for migrations or credentials in source control.
The production PostgreSQL secret is only read from the runner environment.
Plain ZIP exists solely in memory. The encrypted .asct artifact is verified
before writing and should be downloaded with an independently stored password.

By design NO scheduled backup runs until the repository owner creates:
  secrets.CT_BACKUP_DATABASE_URL
  secrets.CT_BACKUP_ENCRYPTION_PASSPHRASE
  variables.CT_BACKUP_ENABLED = true
"""
from datetime import datetime, timezone
import os
from pathlib import Path
import tempfile

from scripts.postgres_backup import export_postgres_backup
from scripts.postgres_encrypted_backup import (
    encrypt_export_zip, inspect_encrypted_export,
)

OUTPUT_PREFIX = "as-control-tower-encrypted-"


def generate_encrypted_backup(url, password):
    """Build + decrypt-verify backup completely in memory.

    Returns (status, ciphertext, safe_summary), never plaintext rows or URL.
    The caller is responsible for safely storing only the ciphertext.
    """
    if not isinstance(url, str) or not url or not isinstance(password, str):
        return "missing_configuration", None, None
    status, plain_zip = export_postgres_backup(url)
    if status != "ok" or not isinstance(plain_zip, bytes):
        return "backup_failed", None, None
    status, ciphertext = encrypt_export_zip(plain_zip, password)
    # Don't leave accidental references to plaintext on later failure paths.
    del plain_zip
    if status != "encrypted" or not isinstance(ciphertext, bytes):
        return "encryption_failed", None, None
    verify_status, summary = inspect_encrypted_export(ciphertext, password)
    if verify_status != "verified_encrypted" or summary is None:
        return "verification_failed", None, None
    if summary["table_count"] != 26:
        return "verification_failed", None, None
    return "ok", ciphertext, {
        "tables": summary["table_count"],
        "rows": summary["row_count"],
        "sha256": summary["encrypted_sha256"],
    }


def write_encrypted_artifact(ciphertext, destination):
    """Use 0600 permissions and an atomic rename; do not create plaintext ZIP."""
    if not isinstance(ciphertext, bytes) or not ciphertext:
        raise ValueError("missing_ciphertext")
    output = Path(destination)
    output.parent.mkdir(parents=True, exist_ok=True)
    if output.exists() or output.is_symlink():
        raise ValueError("destination_exists")
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="wb", dir=output.parent, prefix=".asct-", delete=False
        ) as handle:
            temporary = Path(handle.name)
            os.chmod(temporary, 0o600)
            handle.write(ciphertext)
            handle.flush()
            os.fsync(handle.fileno())
        # Caller generates timestamp+random suffix. Refuse overwrite.
        if output.exists() or output.is_symlink():
            raise ValueError("destination_exists")
        os.rename(temporary, output)
        os.chmod(output, 0o600)
    finally:
        if temporary is not None and temporary.exists():
            temporary.unlink()


def main():
    if os.getenv("CT_BACKUP_ENABLED") != "true":
        print("DISABLED: owner has not enabled scheduled backups")
        return 0
    url = os.getenv("CT_BACKUP_DATABASE_URL", "")
    password = os.getenv("CT_BACKUP_ENCRYPTION_PASSPHRASE", "")
    # Never log either secret or exception/driver errors.
    status, encrypted, summary = generate_encrypted_backup(url, password)
    if status != "ok":
        print("ERROR: encrypted backup not produced (" + status + ")")
        return 1
    root = os.getenv("CT_BACKUP_OUTPUT_DIR", "")
    if not root:
        print("ERROR: configured encrypted output directory is required")
        return 1
    try:
        # A unique GitHub run can be re-run; timestamp + random suffix avoids
        # overwriting a prior artifact within the same job.
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        filename = OUTPUT_PREFIX + stamp + "-" + os.urandom(4).hex() + ".asct"
        write_encrypted_artifact(encrypted, Path(root) / filename)
    except Exception:
        print("ERROR: encrypted output could not be saved")
        return 1
    print(
        f"SUCCESS: {summary['tables']} tables; {summary['rows']} rows; "
        f"encrypted SHA256={summary['sha256']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
