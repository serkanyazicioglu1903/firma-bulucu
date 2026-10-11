"""Conservative, read-only acceptance report for AS Control Tower on ct_app.

Never mistake zero anomalies on empty tables for tested business workflows.
This report is advisory; it neither approves production finance nor writes data.
"""
from scripts.postgres_operational_read import read_operational_counts
from scripts.postgres_reconciliation import check_operational_consistency
from scripts.postgres_company_scope import assess_company_scope

WORKFLOW_TABLES = {
    "CRM / Müşteri": ("customers",),
    "Satın Alma": ("purchase_orders", "shipments"),
    "Stok": ("inventory_lots",),
    "Kalite": ("quality_cases",),
    "Finans": ("payables", "receivables", "finance_transactions"),
}


def evaluate_acceptance(url):
    """Safe aggregate-only status with explicit unverifiable release gates."""
    counts_status, counts = read_operational_counts(url)
    if counts_status != "ok":
        return {"status": "failed", "areas": [], "critical": None}
    integrity = check_operational_consistency(url)
    if integrity["status"] not in ("ok", "issues_found"):
        return {"status": "failed", "areas": [], "critical": None}

    # Check structural legal-entity ownership without fetching company data.
    # Both businesses must not share unlabelled financial / stock ledgers.
    company_scope = assess_company_scope(url)
    if company_scope["status"] != "review_required":
        return {"status": "failed", "areas": [], "critical": None}
    untagged = company_scope["without_direct_entity"]
    if untagged:
        company_gate = (
            f"Tüzel kişi ayrımı: {len(untagged)} kritik operasyon/finans tablosunda "
            "doğrudan şirket sahipliği alanı görünmüyor; dolaylı bağlar, "
            "yetkiler ve şirket bazlı muhasebe incelenmeden canlı onay yok."
        )
    else:
        company_gate = (
            "Tüzel kişi alanları mevcut; şirket bazlı erişim, belgeler ve "
            "banka/finans kayıtlarının yalıtımı henüz doğrulanmadı."
        )

    critical = sum(
        x["count"] for x in integrity["checks"]
        if x["severity"] == "critical"
    )
    warning = sum(
        x["count"] for x in integrity["checks"]
        if x["severity"] == "warning"
    )
    areas = []
    for area, tables in WORKFLOW_TABLES.items():
        row_count = sum(int(counts.get(t, 0)) for t in tables)
        areas.append({
            "area": area,
            "record_count": row_count,
            "status": "Veri yok — canlı iş akışı sınanmadı"
            if row_count == 0 else
            "Kayıt mevcut — sadece temel veri bütünlüğü kontrol edildi",
        })
    # Don't mark application production-ready even if all aggregates are zero.
    return {
        "status": "critical_issues" if critical else "review_required",
        "areas": areas,
        "critical": critical,
        "warnings": warning,
        "checks_executed": len(integrity["checks"]),
        "company_scope": company_scope,
        "external_gates": (
            company_gate,
            "Geri yükleme tatbikatı: doğrulanmadı",
            "Supabase otomatik yedek saklama politikası: doğrulanmadı",
            "Eşzamanlı kullanıcı ve banka mutabakatı: canlıda doğrulanmadı",
        ),
    }
