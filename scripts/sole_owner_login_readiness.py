"""Offline, non-mutating first-login preflight for the sole-owner four-company pilot.

Inputs are operator-supplied *server-side* config snapshots, not browser data.
Do not log inputs: they may contain credentials. The result is aggregate only.
No database access, user changes, grants, deployments or production approval.
"""
import re

_HASH = re.compile(r"^pbkdf2_sha256\$(\d+)\$([0-9a-f]{16,128})\$([0-9a-f]{64})$")
_LOGIN = re.compile(r"^[a-z0-9][a-z0-9._@-]{0,127}$")


def _blocked(reason):
    return {
        "status": "blocked",
        "issue_codes": (reason,),
        "accounts_reviewed": 0,
        "enabled_accounts": 0,
        "password_hash_format_verified": False,
        "signed_session_configured": False,
        "credentials_authenticated": False,
        "other_accounts_disabled_in_production": False,
        "production_authorized": False,
    }


def review_owner_login_config(app_users_json, signing_key, approved_login,
                              legacy_password_present=False):
    """Inspect an in-memory configuration without exposing any account/secret.

    APP_USERS_JSON is parsed like security_admin.load_users, but requires
    explicit boolean enabled flags to avoid bool("false") == True. This
    validator deliberately does not read Streamlit secrets or validate a
    password. A valid *format* is not proof of the real server configuration.
    """
    import json

    if not isinstance(approved_login, str) or not _LOGIN.fullmatch(approved_login):
        return _blocked("owner_login_not_reviewed")
    if legacy_password_present is not False:
        return _blocked("legacy_password_fallback_present")
    if not isinstance(app_users_json, str) or not app_users_json.strip():
        return _blocked("explicit_user_registry_required")
    try:
        parsed = json.loads(app_users_json)
    except (ValueError, TypeError):
        return _blocked("invalid_user_registry")
    if isinstance(parsed, dict):
        parsed = parsed.get("users")
    if not isinstance(parsed, list) or not 0 < len(parsed) <= 100:
        return _blocked("invalid_user_registry")

    seen = set()
    owner = None
    active = 0
    for item in parsed:
        if not isinstance(item, dict):
            return _blocked("invalid_user_registry")
        raw_login = item.get("username")
        if not isinstance(raw_login, str):
            return _blocked("invalid_user_registry")
        login = raw_login.strip().lower()
        if not _LOGIN.fullmatch(login) or login in seen:
            return _blocked("invalid_or_duplicate_login")
        seen.add(login)
        if type(item.get("enabled")) is not bool:
            return _blocked("explicit_boolean_enabled_required")
        if not isinstance(item.get("role"), str):
            return _blocked("invalid_role")
        role = item["role"].upper()
        if role not in {"ADMIN", "SALES", "PURCHASING", "FINANCE", "QUALITY", "VIEWER"}:
            return _blocked("invalid_role")
        # Never permit plaintext fallback, even on a disabled account.
        if item.get("password"):
            return _blocked("plaintext_password_present")
        if item["enabled"]:
            active += 1
            if login != approved_login or role != "ADMIN":
                return _blocked("another_account_enabled")
            owner = item
        if login == approved_login and (not item["enabled"] or role != "ADMIN"):
            return _blocked("owner_not_enabled_admin")

    if owner is None or active != 1:
        return _blocked("sole_owner_not_found")
    match = _HASH.fullmatch(owner.get("password_hash", "")) if isinstance(
        owner.get("password_hash"), str
    ) else None
    if not match or not 200_000 <= int(match.group(1)) <= 1_000_000:
        return _blocked("strong_password_hash_required")
    if (not isinstance(signing_key, str) or not 32 <= len(signing_key) <= 4096
            or len(set(signing_key)) < 12):
        return _blocked("server_session_signing_key_required")
    return {
        "status": "review_required",
        "issue_codes": (),
        "accounts_reviewed": len(seen),
        "enabled_accounts": 1,
        "password_hash_format_verified": True,
        "signed_session_configured": True,
        "credentials_authenticated": False,
        "other_accounts_disabled_in_production": False,
        "production_authorized": False,
    }
