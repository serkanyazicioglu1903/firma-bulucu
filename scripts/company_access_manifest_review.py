"""Offline-only, fail-closed four-company account-to-permission plan review.

This module has NO database connection or write capability and NEVER imports
production APP_USERS_JSON. Callers provide a *reviewed* account registry and
an independently prepared plan. Real credentials are ignored by the snapshot,
and results never return usernames or identifiers.

No ADMIN/holding wildcard or role gets any implicit company permission.
A successful structural review remains review_required, not approval to
populate company_read_grants/company_write_grants or activate any live flag.
"""
import hashlib
import json
import re

from scripts.group_company_catalog import COMPANY_LABELS

USER = re.compile(r"^[a-z0-9][a-z0-9._@-]{0,127}$")
EVIDENCE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/-]{5,127}$")
HEX64 = re.compile(r"^[0-9a-f]{64}$")
ROLES = frozenset({"ADMIN", "SALES", "PURCHASING", "FINANCE", "QUALITY", "VIEWER"})
# Only roles with isolated synthetic write implementations qualify for
# eventual *review*, not production write privileges.
WRITE_REHEARSAL_ROLES = frozenset({"ADMIN", "PURCHASING", "FINANCE", "QUALITY"})
MAX_USERS = 100
MAX_GRANTS_PER_USER = len(COMPANY_LABELS)


def _account_index(accounts):
    """Validate identities without copying secrets to output or fingerprint."""
    if not isinstance(accounts, (list, tuple)) or not 0 < len(accounts) <= MAX_USERS:
        raise ValueError("invalid_registry")
    index = {}
    for entry in accounts:
        if not isinstance(entry, dict):
            raise ValueError("invalid_registry")
        user, role, enabled = (
            entry.get("username"), entry.get("role"), entry.get("enabled")
        )
        if (not isinstance(user, str) or not USER.fullmatch(user)
                or not isinstance(role, str) or role not in ROLES
                or type(enabled) is not bool or user in index):
            raise ValueError("invalid_registry")
        index[user] = {"role": role, "enabled": enabled}
    return index


def registry_fingerprint(accounts):
    """SHA256 detects registry drift; it is NOT an identity signature.

    This only includes username, verified role and enabled status. Real
    passwords, password hashes, tokens and secret metadata are excluded.
    """
    index = _account_index(accounts)
    canonical = {
        "version": "company-account-review-v1",
        "accounts": [
            {"username": user, **index[user]} for user in sorted(index)
        ],
    }
    return hashlib.sha256(json.dumps(
        canonical, sort_keys=True, separators=(",", ":"), ensure_ascii=True,
    ).encode("utf-8")).hexdigest()


def _blocked(issue):
    return {
        "status": "blocked",
        "issue_codes": (issue,),
        "reviewed_accounts": 0,
        "enabled_accounts": 0,
        "proposed_company_reads": 0,
        "proposed_company_writes": 0,
        "real_permissions_granted": False,
        "production_authorized": False,
    }


def review_permission_manifest(accounts, manifest):
    """Count exact, evidence-backed access decisions without granting them.

    Manifest v1:
    {
      "source_sha256": registry_fingerprint(accounts),
      "decisions": [
        {"username": "...", "role": "VIEWER", "enabled": true,
         "decision_ref": "FILE-123456",
         "grants": [{"company_code": "AS_ILERI_GIDA",
                     "can_read": true, "can_write": false,
                     "evidence_ref": "FILE-123456"}]}
      ]
    }

    Exactly one decision is required for EVERY registry user, including
    disabled/zero-grant accounts. No roles/companies are inferred.
    """
    try:
        index = _account_index(accounts)
    except ValueError:
        return _blocked("invalid_registry")
    if (not isinstance(manifest, dict)
            or set(manifest) != {"source_sha256", "decisions"}
            or not isinstance(manifest["source_sha256"], str)
            or not HEX64.fullmatch(manifest["source_sha256"])
            or manifest["source_sha256"] != registry_fingerprint(accounts)):
        return _blocked("stale_or_invalid_source")
    decisions = manifest["decisions"]
    if not isinstance(decisions, list) or len(decisions) != len(index):
        return _blocked("incomplete_decisions")

    seen = set()
    reads = writes = 0
    for decision in decisions:
        if not isinstance(decision, dict) or set(decision) != {
            "username", "role", "enabled", "decision_ref", "grants"
        }:
            return _blocked("invalid_decision")
        user = decision["username"]
        if (not isinstance(user, str) or user not in index or user in seen
                or decision["role"] != index[user]["role"]
                or type(decision["enabled"]) is not bool
                or decision["enabled"] != index[user]["enabled"]
                or not isinstance(decision["decision_ref"], str)
                or not EVIDENCE.fullmatch(decision["decision_ref"])):
            return _blocked("invalid_decision")
        seen.add(user)
        grants = decision["grants"]
        if not isinstance(grants, list) or len(grants) > MAX_GRANTS_PER_USER:
            return _blocked("invalid_grants")
        if not index[user]["enabled"] and grants:
            return _blocked("disabled_user_granted")

        codes = set()
        for grant in grants:
            if not isinstance(grant, dict) or set(grant) != {
                "company_code", "can_read", "can_write", "evidence_ref"
            }:
                return _blocked("invalid_grants")
            code = grant["company_code"]
            if (not isinstance(code, str) or code not in COMPANY_LABELS
                    or code in codes
                    or type(grant["can_read"]) is not bool
                    or type(grant["can_write"]) is not bool
                    or grant["can_read"] is not True
                    or not isinstance(grant["evidence_ref"], str)
                    or not EVIDENCE.fullmatch(grant["evidence_ref"])):
                return _blocked("invalid_grants")
            if grant["can_write"] and index[user]["role"] not in WRITE_REHEARSAL_ROLES:
                return _blocked("role_write_not_rehearsed")
            codes.add(code)
            reads += 1
            writes += int(grant["can_write"])
    if seen != set(index):
        return _blocked("incomplete_decisions")

    return {
        "status": "review_required",
        "issue_codes": (),
        "reviewed_accounts": len(index),
        "enabled_accounts": sum(int(u["enabled"]) for u in index.values()),
        "proposed_company_reads": reads,
        "proposed_company_writes": writes,
        "real_permissions_granted": False,
        "production_authorized": False,
    }
