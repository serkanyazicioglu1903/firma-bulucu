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


def _signature(username, role, session_id, key):
    message = "\x00".join((username, role, session_id)).encode("utf-8")
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
    return _signature(username, role, session_id, key)


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
    expected = _signature(username, role, session_id, key)
    if not hmac.compare_digest(actual, expected):
        return None
    return username
