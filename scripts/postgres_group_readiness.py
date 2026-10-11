"""Read-only launch readiness for the four AS Control Tower legal entities.

Never infer isolation from labels, zero-row tables or a company column alone.
A live readiness report must fail closed until an independent security,
accounting, backup/restore and multi-company end-to-end review is completed.
No DB connection is opened until a caller explicitly requests assessment.
"""
from scripts.group_company_catalog import review_group_catalog
from scripts.postgres_company_scope import assess_company_scope, CRITICAL_TABLES


def group_preview():
    """A static list; neither legal names nor DB owner IDs are verified."""
    catalog = review_group_catalog()
    return {
        "status": "not_approved",
        "company_count": catalog["entity_count"],
        "companies": tuple({
            "code": item["code"],
            "name": item["display_label"],
            "status": "Kayıt ayrımı henüz doğrulanmadı",
        } for item in catalog["entities"]),
        "production_multi_company_approved": False,
    }


def summarize_group_structure(company_scope):
    """Sanitize metadata into a launch BLOCK, never a GO decision."""
    if not isinstance(company_scope, dict) or company_scope.get("status") != "review_required":
        return {
            "status": "failed",
            "company_count": 4,
            "missing_owner_tables": None,
            "checked_tables": 0,
            "production_multi_company_approved": False,
            "company_finance_verified": False,
            "consolidation_verified": False,
        }
    missing = company_scope.get("without_direct_entity")
    if not isinstance(missing, (tuple, list)):
        return summarize_group_structure(None)
    if any(table not in CRITICAL_TABLES for table in missing):
        return summarize_group_structure(None)
    return {
        "status": "blocked" if missing else "review_required",
        "company_count": 4,
        "missing_owner_tables": len(set(missing)),
        "checked_tables": len(CRITICAL_TABLES),
        "production_multi_company_approved": False,
        "company_finance_verified": False,
        "consolidation_verified": False,
    }


def evaluate_group_readiness(url):
    """Only PostgreSQL schema metadata is read; never fetch financial rows."""
    return summarize_group_structure(assess_company_scope(url))
