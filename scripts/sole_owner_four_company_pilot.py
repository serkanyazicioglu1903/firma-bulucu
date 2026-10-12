"""Read-only, single-owner initial four-company pilot authorization PLAN.

Only the verified owner account may be enabled in the initial pilot roster.
It gets four independently reviewed READ scopes; every WRITE scope stays off.
ALL additional accounts, including ADMIN accounts, must be disabled with
zero grants and no DB role. The operator-supplied owner login is merely a
reviewed reference, never authenticated by this module.

This module has NO production runner, secret reader, DDL or DML. No privileges
are provisioned by passing review. Live migration, backup restoration,
per-user DB authentication, physical data ownership and UI route isolation
are separately required and unverified.
"""
from scripts.company_access_manifest_review import (
    _account_index, EVIDENCE, review_permission_manifest,
)
from scripts.company_user_db_role_manifest import review_app_to_database_roles
from scripts.group_company_catalog import COMPANY_LABELS


def _blocked(reason):
    return {
        "status": "blocked",
        "issue_codes": (reason,),
        "accounts_reviewed": 0,
        "enabled_accounts": 0,
        "company_read_scopes": 0,
        "company_write_scopes": 0,
        "proposed_database_roles": 0,
        "other_accounts_enabled": False,
        "actual_credentials_verified": False,
        "actual_company_grants_created": False,
        "actual_db_roles_created": False,
        "live_company_isolation_verified": False,
        "production_authorized": False,
    }


def review_sole_owner_pilot(accounts, access_plan, db_role_plan,
                            approved_login, approval_ref):
    """Check exact single ADMIN, four distinct READ-only scopes and one DB role.

    All plan inputs must originate from separately authenticated operator
    review. The chosen login is NOT selected from a browser company dropdown.
    The role plan is a PROPOSAL; no user or database session is created.
    """
    try:
        users = _account_index(accounts)
    except (ValueError, TypeError):
        return _blocked("invalid_account_registry")
    if (not isinstance(approved_login, str)
            or approved_login not in users
            or not isinstance(approval_ref, str)
            or not EVIDENCE.fullmatch(approval_ref)):
        return _blocked("owner_identity_not_reviewed")
    active = [login for login, attrs in users.items() if attrs["enabled"]]
    if active != [approved_login] or users[approved_login]["role"] != "ADMIN":
        return _blocked("not_exclusive_active_admin")

    scopes = review_permission_manifest(accounts, access_plan)
    if scopes["status"] != "review_required":
        return _blocked("invalid_company_permission_manifest")
    if (not isinstance(access_plan, dict)
            or not isinstance(access_plan.get("decisions"), list)):
        return _blocked("invalid_company_permission_manifest")
    owned = [entry for entry in access_plan["decisions"]
             if entry["username"] == approved_login]
    if len(owned) != 1:
        return _blocked("owner_permission_decision_missing")
    for entry in access_plan["decisions"]:
        if entry["username"] != approved_login and entry["grants"]:
            return _blocked("other_account_has_grants")
    owner = owned[0]
    grants = owner["grants"]
    if (len(grants) != len(COMPANY_LABELS)
            or {g["company_code"] for g in grants} != set(COMPANY_LABELS)
            or any(g["can_read"] is not True or g["can_write"] is not False
                   for g in grants)):
        return _blocked("exact_four_read_only_scopes_required")

    roles = review_app_to_database_roles(accounts, db_role_plan)
    if (roles["status"] != "review_required"
            or roles["proposed_role_bindings"] != 1):
        return _blocked("invalid_single_database_role_plan")
    bindings = db_role_plan["bindings"]
    owner_bindings = [entry for entry in bindings
                      if entry["username"] == approved_login]
    if (len(owner_bindings) != 1
            or not isinstance(owner_bindings[0]["db_role"], str)):
        return _blocked("owner_db_role_missing")

    # Only a structural proposal. Never return login, DB role, proof refs,
    # passwords/hashes, or client-controlled company identifiers.
    return {
        "status": "review_required",
        "issue_codes": (),
        "accounts_reviewed": len(users),
        "enabled_accounts": 1,
        "company_read_scopes": len(COMPANY_LABELS),
        "company_write_scopes": 0,
        "proposed_database_roles": 1,
        "other_accounts_enabled": False,
        "actual_credentials_verified": False,
        "actual_company_grants_created": False,
        "actual_db_roles_created": False,
        "live_company_isolation_verified": False,
        "production_authorized": False,
    }
