"""Compare an archive against an independently retained SHA-256 reference.

This *only* compares file bytes against a user-provided trusted reference.
It cannot prove where the reference originated, certify database backups,
or guarantee the archive is restorable. No database, file system or network IO.
"""
import hashlib
import hmac
import re

from scripts.postgres_backup_verify import MAX_FILE_BYTES
from scripts.postgres_encrypted_backup import MAX_ENCRYPTED_BYTES

_HEX64 = re.compile(r"^[0-9a-fA-F]{64}$")
MAX_ALLOWED = max(MAX_FILE_BYTES, MAX_ENCRYPTED_BYTES)


def compare_saved_sha256(payload, expected_hex):
    """Return matched | mismatch | no_reference | invalid_reference | invalid_file.

    Never return archive content or the caller-provided expected hash.
    A matching reference should be stored separately at export time, outside
    the ZIP/ASCT file and not obtained from the uploaded archive itself.
    """
    if not isinstance(payload, bytes) or not 0 < len(payload) <= MAX_ALLOWED:
        return "invalid_file"
    if expected_hex is None or expected_hex == "":
        return "no_reference"
    if not isinstance(expected_hex, str):
        return "invalid_reference"
    cleaned = expected_hex.strip()
    if not _HEX64.fullmatch(cleaned):
        return "invalid_reference"
    actual = hashlib.sha256(payload).digest()
    try:
        target = bytes.fromhex(cleaned)
    except ValueError:
        return "invalid_reference"
    return "matched" if hmac.compare_digest(actual, target) else "mismatch"
