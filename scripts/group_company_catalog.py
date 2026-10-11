"""Review-only AS Control Tower group company labels and scope guard.

The owner confirmed all four entities are incorporated. Labels below are
business-facing names, NOT verified legal-register names, tax numbers, entity
primary keys or an approved production seed. This module never connects to a
database, modifies tables or grants user rights. The server must validate the
real authenticated session AND map IDs to verified legal entities separately.
"""
from types import MappingProxyType

# Stable internal handles (not Supabase row IDs or tax identifiers).
COMPANY_LABELS = MappingProxyType({
    "AS_ILERI_GIDA": "AS İleri Gıda",
    "PLANET_INGREDIENTS": "Planet Ingredients",
    "AS_FOOD_GLOBAL": "AS Food Global Ltd",
    "AS_ILERI_HOLDING": "AS İleri Holding A.Ş.",
})


class CompanyScopeDenied(ValueError):
    """Safe, non-secret code for absent/unauthorized company selection."""

    def __init__(self):
        super().__init__("company_scope_denied")


def review_group_catalog():
    """Display-only configuration; never a production-verification signal."""
    return {
        "status": "review_required",
        "incorporation_user_confirmed": True,
        "verified_legal_names": False,
        "entity_count": len(COMPANY_LABELS),
        "entities": tuple(
            {"code": code, "display_label": label}
            for code, label in COMPANY_LABELS.items()
        ),
        "finance_isolation_verified": False,
        "consolidation_verified": False,
    }


def require_explicit_company_scope(company_code, granted_codes):
    """Deny by default; explicit single-company selection AND verified grants.

    `granted_codes` must originate from independent, authenticated,
    server-side authorization. It is never accepted from an untrusted UI.
    An ADMIN gets all four only if all four are explicitly granted; no
    cross-company wildcard or implicit holding-company super-access.
    """
    if not isinstance(company_code, str) or company_code not in COMPANY_LABELS:
        raise CompanyScopeDenied()
    if isinstance(granted_codes, (str, bytes, dict)):
        raise CompanyScopeDenied()
    if not isinstance(granted_codes, (tuple, list, frozenset, set)):
        raise CompanyScopeDenied()
    if company_code not in granted_codes:
        raise CompanyScopeDenied()
    return company_code
