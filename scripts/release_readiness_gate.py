"""Offline, fail-closed release readiness gate for AS Control Tower.

Never opens a database, prints credentials, or changes production state.
A green CI run is not evidence of production tenancy, data migration or grants.
"""
import json
import os
from pathlib import Path

from scripts.group_company_catalog import COMPANY_LABELS

REQUIRED_EVIDENCE = (
    "four_company_rls_verified",
    "dedicated_login_roles_verified",
    "four_company_data_migration_reconciled",
    "end_to_end_workflows_verified",
    "backup_restore_verified",
    "owner_approved_release",
)


def assess_release(evidence=None):
    """Return an honest release verdict; evidence must be explicit booleans."""
    evidence = evidence if isinstance(evidence, dict) else {}
    checks = {key: evidence.get(key) is True for key in REQUIRED_EVIDENCE}
    return {
        "project": "AS Control Tower",
        "companies": list(COMPANY_LABELS.values()),
        "evidence_complete": all(checks.values()),
        "release_ready": False,
        "checks": checks,
        "missing": [key for key, ok in checks.items() if not ok],
        "note": "Evidence complete does not authorize deployment. Live grants, access and owner approval must be independently verified.",
    }


def main():
    # Evidence must be an explicit local JSON file; never accept a CLI claim of readiness.
    path = os.environ.get("CT_RELEASE_EVIDENCE_FILE", "")
    evidence = {}
    if path:
        try:
            data = json.loads(Path(path).read_text(encoding="utf-8"))
            if isinstance(data, dict):
                evidence = data
        except (OSError, ValueError):
            pass
    report = assess_release(evidence)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["evidence_complete"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
