"""Offline-only reviewed app-login -> PostgreSQL-role binding contract.

No APP_USERS_JSON is loaded by this module and nothing is written. The actual
production user registry must be loaded by a separately authenticated server
admin workflow, with all private fields kept confidential. All mappings
remain UNAPPROVED until a real DB-role probe and rights/restore review.
"""
from scripts.company_access_manifest_review import (
    _account_index, registry_fingerprint, EVIDENCE,
)
from scripts.company_db_role_preflight import _ROLE, _DENIED_ROLES

def _blocked(reason):
    return {
        "status": "blocked", "issue_codes": (reason,),
        "reviewed_users": 0, "proposed_role_bindings": 0,
        "database_login_verified": False,
        "company_permissions_granted": False,
        "production_authorized": False,
    }


def review_app_to_database_roles(accounts, plan):
    """No inferred login/role, group ADMIN wildcard or reused DB identity.

    Expects all real users, including disabled accounts; each enabled user
    explicitly receives ONE distinct proposed least-privileged PG role.
    Binding the displayed role string to an actual authenticated database
    session is *not* performed here and must not be trusted from this plan.
    """
    try:
        users = _account_index(accounts)
        source = registry_fingerprint(accounts)
    except (ValueError, TypeError):
        return _blocked("invalid_account_registry")
    if (not isinstance(plan, dict)
            or set(plan) != {"source_sha256", "bindings"}
            or plan["source_sha256"] != source
            or not isinstance(plan["bindings"], list)
            or len(plan["bindings"]) != len(users)):
        return _blocked("stale_or_incomplete_account_plan")
    mapped = set()
    db_roles = set()
    active_count = 0
    for entry in plan["bindings"]:
        if (not isinstance(entry, dict)
                or set(entry) != {"username", "db_role", "evidence_ref"}):
            return _blocked("invalid_binding")
        user, role, evidence = (
            entry["username"], entry["db_role"], entry["evidence_ref"]
        )
        if (not isinstance(user, str) or user not in users or user in mapped
                or not isinstance(evidence, str)
                or not EVIDENCE.fullmatch(evidence)):
            return _blocked("invalid_binding")
        mapped.add(user)
        if not users[user]["enabled"]:
            if role is not None:
                return _blocked("disabled_account_has_db_role")
            continue
        if (not isinstance(role, str) or not _ROLE.fullmatch(role)
                or role in _DENIED_ROLES or role in db_roles):
            return _blocked("invalid_or_reused_db_role")
        db_roles.add(role)
        active_count += 1
    if mapped != set(users) or active_count == 0:
        return _blocked("incomplete_or_inactive_bindings")
    return {
        "status": "review_required",
        "issue_codes": (),
        "reviewed_users": len(users),
        "proposed_role_bindings": active_count,
        "database_login_verified": False,
        "company_permissions_granted": False,
        "production_authorized": False,
    }
