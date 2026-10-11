"""OFFLINE four-company isolation blueprint review covering ALL 26 ct_app tables.

This validates human-prepared architectural DECISIONS, not customer records.
No connection, environment secrets, GRANT, DDL, migration, seed or UI grants.
A structurally complete plan remains REVIEW_REQUIRED, never production-ready.

A named parent/FK path is only a PROPOSAL. Actual database constraints,
row policies, every legacy query, and role grants must be audited separately.
"""
import re

from scripts.group_company_catalog import COMPANY_LABELS
from scripts.postgres_company_full_coverage import REVIEW_GROUPS, _catalog_tables


EVIDENCE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/-]{5,127}$")
FK_FIELD = re.compile(r"^[a-z][a-z0-9_]{0,62}_id$")
ENTITY_LIMIT = 4

# Strategies do not grant access; even proposed "shared" products can include
# confidential pricing and MUST be explicitly approved by legal/security.
ALLOWED_MODES = {
    "direct_owner_required": frozenset({"direct_owner"}),
    "shared_master_decision": frozenset({"direct_owner", "shared_candidate"}),
    "parent_ownership_decision": frozenset({"direct_owner", "parent_scoped"}),
    "derived_ownership_decision": frozenset({"direct_owner", "parent_scoped"}),
    "internal_access_decision": frozenset({"direct_owner", "internal_only"}),
}
assert set(ALLOWED_MODES) == set(REVIEW_GROUPS)


def _blocked(code):
    return {
        "status": "blocked",
        "issue_codes": (code,),
        "reviewed_company_count": 0,
        "reviewed_table_count": 0,
        "proposed_direct_owner_tables": 0,
        "proposed_parent_scoped_tables": 0,
        "proposed_shared_candidates": 0,
        "proposed_internal_only_tables": 0,
        "company_isolation_verified": False,
        "database_constraints_verified": False,
        "row_level_access_verified": False,
        "legal_register_verified": False,
        "production_approved": False,
    }


def review_isolation_blueprint(blueprint):
    """Reject incomplete ownership and access paths without returning input data.

    Input:
      {"companies": [
          {"code": known_code, "legal_name": externally reviewed nonempty name,
           "evidence_ref": opaque legal review document reference}, ...],
       "tables": [
          {"table": one of 26 ct_app tables,
           "mode": "direct_owner" | "parent_scoped" |
                   "shared_candidate" | "internal_only",
           "parent_table": parent table name or null,
           "fk_column": proposed FK column name or null,
           "evidence_ref": opaque design document reference}, ...]}

    Each company and table must appear exactly once. A parent_scoped table
    must reach a directly owned table via an acyclic explicit chain.
    No company labels, raw legal names or evidence refs are returned.

    All validations are offline structural checks; no physical FK check or
    any migration/user-grant authorization occurs.
    """
    if not isinstance(blueprint, dict) or set(blueprint) != {"companies", "tables"}:
        return _blocked("invalid_blueprint")
    companies = blueprint["companies"]
    tables = blueprint["tables"]
    try:
        expected = _catalog_tables()
    except Exception:
        return _blocked("unexpected_schema_inventory")

    if (not isinstance(companies, list) or len(companies) != ENTITY_LIMIT
            or not isinstance(tables, list) or len(tables) != len(expected)):
        return _blocked("incomplete_company_or_table_list")

    found_companies = set()
    for item in companies:
        if not isinstance(item, dict) or set(item) != {
            "code", "legal_name", "evidence_ref"
        }:
            return _blocked("invalid_company_evidence")
        code, name, evidence = (
            item["code"], item["legal_name"], item["evidence_ref"]
        )
        if (not isinstance(code, str) or code not in COMPANY_LABELS
                or code in found_companies
                or not isinstance(name, str) or not 3 <= len(name.strip()) <= 200
                or any(ord(ch) < 32 or ord(ch) == 127 for ch in name)
                or not isinstance(evidence, str)
                or not EVIDENCE.fullmatch(evidence)):
            return _blocked("invalid_company_evidence")
        found_companies.add(code)
    if found_companies != set(COMPANY_LABELS):
        return _blocked("missing_company_evidence")

    groups = {table: group for group, members in REVIEW_GROUPS.items()
              for table in members}
    policies = {}
    for row in tables:
        if not isinstance(row, dict) or set(row) != {
            "table", "mode", "parent_table", "fk_column", "evidence_ref"
        }:
            return _blocked("invalid_table_policy")
        table, mode, parent, field, evidence = (
            row["table"], row["mode"], row["parent_table"],
            row["fk_column"], row["evidence_ref"]
        )
        if (not isinstance(table, str) or table not in expected
                or table in policies or not isinstance(mode, str)
                or mode not in ALLOWED_MODES[groups[table]]
                or not isinstance(evidence, str)
                or not EVIDENCE.fullmatch(evidence)):
            return _blocked("invalid_table_policy")
        if mode == "parent_scoped":
            if (not isinstance(parent, str) or parent not in expected
                    or parent == table or not isinstance(field, str)
                    or not FK_FIELD.fullmatch(field)):
                return _blocked("invalid_parent_path")
        elif parent is not None or field is not None:
            return _blocked("unexpected_parent_path")
        policies[table] = {"mode": mode, "parent_table": parent}

    if set(policies) != expected:
        return _blocked("incomplete_table_policy")

    # Parent inheritance must terminate at an owner; a shared catalogue,
    # internal administrative table or a cycle can never confer ownership.
    for table, row in policies.items():
        if row["mode"] != "parent_scoped":
            continue
        visited = {table}
        cursor = row["parent_table"]
        while True:
            if cursor in visited:
                return _blocked("cyclic_parent_path")
            visited.add(cursor)
            mode = policies[cursor]["mode"]
            if mode == "direct_owner":
                break
            if mode != "parent_scoped":
                return _blocked("parent_not_company_owned")
            cursor = policies[cursor]["parent_table"]

    return {
        "status": "review_required",
        "issue_codes": (),
        "reviewed_company_count": len(found_companies),
        "reviewed_table_count": len(policies),
        "proposed_direct_owner_tables": sum(
            p["mode"] == "direct_owner" for p in policies.values()
        ),
        "proposed_parent_scoped_tables": sum(
            p["mode"] == "parent_scoped" for p in policies.values()
        ),
        "proposed_shared_candidates": sum(
            p["mode"] == "shared_candidate" for p in policies.values()
        ),
        "proposed_internal_only_tables": sum(
            p["mode"] == "internal_only" for p in policies.values()
        ),
        "company_isolation_verified": False,
        "database_constraints_verified": False,
        "row_level_access_verified": False,
        "legal_register_verified": False,
        "production_approved": False,
    }
