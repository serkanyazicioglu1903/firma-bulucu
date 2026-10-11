"""Signed server session identity for optional four-company review mode.

This is NOT a replacement for the normal login gate. Multi-company read mode
requires APP_USERS_JSON, a separate >=32-character server-only signing key,
and a password-verified login minted by security_admin.login_gate.
A browser-selected company, role label, or unverified session dict is never
accepted as a legal-entity grant. PostgreSQL independently validates grants.
"""
import hashlib
import hmac
import json
import re

from security_admin import _secret, current_user, load_users


SESSION_SIGNATURE_KEY = "ct_company_session_signature"
SIGNING_SECRET_KEY = "CT_COMPANY_SESSION_SIGNING_KEY"


def _signing_key():
    value = _secret(SIGNING_SECRET_KEY, "")
    if not isinstance(value, str) or len(value) < 32:
        return None
    return value.encode("utf-8")


def _user_registry_explicitly_configured():
    raw = _secret("APP_USERS_JSON", "")
    if not isinstance(raw, str) or not raw.strip():
        return False
    try:
        parsed = json.loads(raw)
    except (ValueError, TypeError):
        return False
    if isinstance(parsed, dict):
        parsed = parsed.get("users")
    # Do not mistake an invalid APP_USERS_JSON + legacy password fallback
    # for a configured user directory that supports legal-entity identity.
    return isinstance(parsed, list) and any(
        isinstance(item, dict) and bool(str(item.get("username") or "").strip())
        for item in parsed
    )


# Company review sessions require an actual salted, derived password hash.
# The legacy plain-text password fallback remains a separate app path and
# never grants signed company scope. No password or hash is returned to UI.
_HEX = re.compile(r"^[0-9a-f]+$")


def _credential_binding(account):
    value = account.get("password_hash") if isinstance(account, dict) else None
    if not isinstance(value, str):
        return None
    parts = value.split("$")
    if len(parts) != 4 or parts[0] != "pbkdf2_sha256":
        return None
    try:
        rounds = int(parts[1])
    except ValueError:
        return None
    if (not 200_000 <= rounds <= 1_000_000
            or not 16 <= len(parts[2]) <= 128
            or len(parts[3]) != 64
            or not _HEX.fullmatch(parts[2])
            or not _HEX.fullmatch(parts[3])):
        return None
    return value


def _signature(username, role, session_id, credential_binding, key):
    # Rotating the user's password hash revokes the previous company scope
    # immediately at the next DB read without changing the Streamlit login.
    # A role change or account disable is also independently checked.
    message = "\x00".join((
        "company-session-v2", username, role, session_id, credential_binding,
    )).encode("utf-8")
    return hmac.new(key, message, hashlib.sha256).hexdigest()


def sign_verified_company_login(user, session_id):
    """Called ONLY after the existing username/password check succeeds.

    Returns a signature for Streamlit server session storage, or None.
    Never serialize to the browser or display in the UI.
    """
    key = _signing_key()
    if not key or not _user_registry_explicitly_configured():
        return None
    if not isinstance(user, dict) or not isinstance(session_id, str):
        return None
    username = user.get("username")
    role = user.get("role")
    if not isinstance(username, str) or not isinstance(role, str):
        return None
    if not session_id or len(session_id) > 128 or not username:
        return None
    # Configured account details, not caller-supplied user role, are authoritative.
    matches = [u for u in load_users()
               if u.get("username") == username and u.get("enabled")
               and u.get("role") == role]
    if len(matches) != 1:
        return None
    credential = _credential_binding(matches[0])
    if credential is None:
        return None
    return _signature(username, role, session_id, credential, key)


def verified_company_principal(session_state):
    """Return server-verified principal, otherwise None (fail closed).

    A manually supplied `ct_user` object and a fake `ct_session_id` without
    an HMAC minted after password login cannot unlock company reads.
    """
    key = _signing_key()
    if not key or not _user_registry_explicitly_configured():
        return None
    user = current_user()
    if not isinstance(user, dict) or not callable(getattr(session_state, "get", None)):
        return None
    username = user.get("username")
    role = user.get("role")
    session_id = session_state.get("ct_session_id")
    actual = session_state.get(SESSION_SIGNATURE_KEY)
    if not all(isinstance(v, str) and bool(v) for v in (
        username, role, session_id, actual
    )):
        return None
    if len(session_id) > 128 or len(actual) != 64:
        return None
    matches = [u for u in load_users()
               if u.get("username") == username and u.get("enabled")
               and u.get("role") == role]
    if len(matches) != 1:
        return None
    credential = _credential_binding(matches[0])
    if credential is None:
        return None
    expected = _signature(username, role, session_id, credential, key)
    if not hmac.compare_digest(actual, expected):
        return None
    return username
