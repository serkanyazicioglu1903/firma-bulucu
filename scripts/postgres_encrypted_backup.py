"""Password-encrypted AS Control Tower ZIP for secure offsite storage.

Uses scrypt N=2**14, r=8, p=1 and AES-256-GCM with unique random salt/nonce,
authenticated magic/version header, and an in-memory only plaintext ZIP.

The passphrase NEVER enters PostgreSQL, GitHub, logs or the archive. The user
must keep it separately; lost passphrases make the encrypted backup unreadable.
This is a manual backup, not automated provider backups or disaster recovery.
"""
import hashlib
import os

from scripts.postgres_backup_verify import MAX_FILE_BYTES, inspect_export_zip

MAGIC = b"ASCTENC1"
SALT_LEN = 16
NONCE_LEN = 12
TAG_LEN = 16
MAX_ENCRYPTED_BYTES = MAX_FILE_BYTES + len(MAGIC) + SALT_LEN + NONCE_LEN + TAG_LEN


def _acceptable_password(passphrase):
    return (
        isinstance(passphrase, str)
        and 14 <= len(passphrase) <= 256
        and len(set(passphrase)) >= 5
        and not any(ord(c) < 32 for c in passphrase)
    )


def _derive_key(passphrase, salt):
    return hashlib.scrypt(
        passphrase.encode("utf-8"),
        salt=salt, n=2**14, r=8, p=1, dklen=32,
    )


def encrypt_export_zip(archive, passphrase):
    """(status, encrypted_bytes) when ZIP checksums and schema are valid."""
    if not _acceptable_password(passphrase):
        return "weak_passphrase", None
    status, _ = inspect_export_zip(archive)
    if status != "verified_format":
        return "invalid_archive", None
    try:
        from cryptography.hazmat.primitives.ciphers.aead import AESGCM

        salt = os.urandom(SALT_LEN)
        nonce = os.urandom(NONCE_LEN)
        key = _derive_key(passphrase, salt)
        aad = MAGIC + salt
        encrypted = AESGCM(key).encrypt(nonce, archive, aad)
        return "encrypted", MAGIC + salt + nonce + encrypted
    except Exception:
        return "failed", None


def decrypt_export_zip(ciphertext, passphrase):
    """(status, zip_bytes) in memory. Does not open a DB or write files."""
    if (not isinstance(ciphertext, bytes)
            or not (len(MAGIC) + SALT_LEN + NONCE_LEN + TAG_LEN <
                    len(ciphertext) <= MAX_ENCRYPTED_BYTES)
            or not ciphertext.startswith(MAGIC)):
        return "invalid_file", None
    if not isinstance(passphrase, str) or len(passphrase) > 256:
        return "wrong_password_or_corrupt", None
    try:
        from cryptography.hazmat.primitives.ciphers.aead import AESGCM
        salt_start = len(MAGIC)
        nonce_start = salt_start + SALT_LEN
        data_start = nonce_start + NONCE_LEN
        salt = ciphertext[salt_start:nonce_start]
        nonce = ciphertext[nonce_start:data_start]
        aad = MAGIC + salt
        key = _derive_key(passphrase, salt)
        zip_bytes = AESGCM(key).decrypt(nonce, ciphertext[data_start:], aad)
        if len(zip_bytes) > MAX_FILE_BYTES:
            return "invalid_file", None
        return "decrypted", zip_bytes
    except Exception:
        # Do not distinguish wrong password from a tampered archive.
        return "wrong_password_or_corrupt", None


def inspect_encrypted_export(ciphertext, passphrase):
    """Validate encrypted file and its inner ZIP without returning row data."""
    status, zip_bytes = decrypt_export_zip(ciphertext, passphrase)
    if status != "decrypted":
        return status, None
    validation, report = inspect_export_zip(zip_bytes)
    if validation != "verified_format":
        return "corrupt_or_wrong_format", None
    safe_summary = dict(report)
    safe_summary["encrypted_sha256"] = hashlib.sha256(ciphertext).hexdigest()
    return "verified_encrypted", safe_summary
