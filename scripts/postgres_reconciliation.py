"""Read-only consistency reconciliation for ct_app purchase/stock/quality/finance.

This audit never repairs or mutates records. All queries are fixed,
aggregate-only, and run in one repeatable-read transaction to avoid
inconsistent cross-table snapshots. Sensitive business rows, credentials,
and PostgreSQL exception messages are not returned to the UI.
"""
from scripts.postgres_connection import sslmode_for
from scripts.staging_transaction_smoke import validate_test_url
from scripts.staging_validate import validate_staging_structure

# (machine_id, Turkish label, business area, severity, fixed aggregate query)
# Thresholds account for common sub-gram floating point differences.
CHECKS = (
    (
        "missing_inventory_receipt",
        "Stoğa alındı işaretli ancak lot kaydı olmayan sevkiyat",
        "Satın Alma / Stok",
        "critical",
        """
        SELECT COUNT(*) FROM ct_app.shipments s
        WHERE s.received_to_stock=1
          AND NOT EXISTS (
              SELECT 1 FROM ct_app.inventory_lots l WHERE l.shipment_id=s.id
          )
        """,
    ),
    (
        "unreceived_inventory_lot",
        "Stoğa alınmamış sevkiyata bağlı stok lotu",
        "Satın Alma / Stok",
        "critical",
        """
        SELECT COUNT(*) FROM ct_app.inventory_lots l
        JOIN ct_app.shipments s ON s.id=l.shipment_id
        WHERE COALESCE(s.received_to_stock,0)<>1
        """,
    ),
    (
        "shipment_over_order",
        "Sipariş miktarını aşan aktif sevkiyat grubu",
        "Satın Alma / Stok",
        "critical",
        """
        SELECT COUNT(*) FROM (
          SELECT po.id
          FROM ct_app.purchase_orders po
          JOIN ct_app.shipments s ON s.purchase_order_id=po.id
          WHERE COALESCE(s.status,'')<>'İptal'
          GROUP BY po.id,po.quantity_kg
          HAVING SUM(COALESCE(s.quantity_kg,0)) >
                 COALESCE(po.quantity_kg,0)+0.001
        ) groups_over_limit
        """,
    ),
    (
        "invalid_stock_quantities",
        "Negatif veya müsait miktarı aşan stok blokajı",
        "Stok / Kalite",
        "critical",
        """
        SELECT COUNT(*) FROM ct_app.inventory_lots l
        WHERE COALESCE(l.quantity_received_kg,0)<0
           OR COALESCE(l.quantity_available_kg,0)<-0.001
           OR COALESCE(l.quantity_reserved_kg,0)<-0.001
           OR COALESCE(l.quality_hold_kg,0)<-0.001
           OR (COALESCE(l.quantity_reserved_kg,0)
                 + COALESCE(l.quality_hold_kg,0)) >
                 COALESCE(l.quantity_available_kg,0)+0.001
        """,
    ),
    (
        "inconsistent_quality_hold",
        "HOLD durumu ve bloke miktarı uyumsuz stok lotu",
        "Stok / Kalite",
        "critical",
        """
        SELECT COUNT(*) FROM ct_app.inventory_lots l
        WHERE (COALESCE(l.quality_hold_kg,0)>0
               AND COALESCE(l.quality_status,'Released')<>'HOLD')
           OR (l.quality_status='HOLD'
               AND COALESCE(l.quality_hold_kg,0)<=0)
        """,
    ),
    (
        "quality_case_link_mismatch",
        "HOLD lotu ile kalite dosyası eşleşmiyor",
        "Stok / Kalite",
        "critical",
        """
        SELECT COUNT(*) FROM ct_app.inventory_lots l
        LEFT JOIN ct_app.quality_cases q ON q.id=l.quality_case_id
        WHERE l.quality_status='HOLD'
          AND (l.quality_case_id IS NULL
               OR q.id IS NULL
               OR q.inventory_lot_id IS DISTINCT FROM l.id)
        """,
    ),
    (
        "overpaid_supplier",
        "Tutarı aşan veya negatif tedarikçi ödeme kaydı",
        "Finans",
        "critical",
        """
        SELECT COUNT(*) FROM ct_app.payables p
        WHERE COALESCE(p.paid_amount,0)<-0.0001
           OR COALESCE(p.paid_amount,0)>COALESCE(p.amount,0)+0.0001
        """,
    ),
    (
        "overcollected_customer",
        "Tutarı aşan veya negatif müşteri tahsilatı",
        "Finans",
        "critical",
        """
        SELECT COUNT(*) FROM ct_app.receivables r
        WHERE COALESCE(r.paid_amount,0)<-0.0001
           OR COALESCE(r.paid_amount,0)>COALESCE(r.amount,0)+0.0001
        """,
    ),
    (
        "duplicate_bank_reference",
        "Aynı banka hesabında mükerrer ödeme veya tahsilat referansı",
        "Finans",
        "critical",
        """
        SELECT COUNT(*) FROM (
          SELECT account_id,transaction_type,reference
          FROM ct_app.finance_transactions
          WHERE account_id IS NOT NULL
            AND reference IS NOT NULL
            AND TRIM(reference)<>''
            AND transaction_type IN ('Ödeme','Tahsilat')
          GROUP BY account_id,transaction_type,reference
          HAVING COUNT(*)>1
        ) duplicated_references
        """,
    ),
    (
        "negative_bank_balance",
        "Negatif banka/kasa bakiyesi (kredili hesap olabilir)",
        "Finans",
        "warning",
        """
        SELECT COUNT(*) FROM ct_app.cash_accounts
        WHERE COALESCE(balance,0)<-0.0001
        """,
    ),
)

_EXPECTED_ID_COUNT = 10


def check_operational_consistency(url):
    """Return safe status + aggregate-only findings, never row-level data.

    status = ok | issues_found | invalid_url | schema_mismatch | failed
    Successful checks list only labels, count and severity, never IDs/values.
    """
    if not validate_test_url(url):
        return {"status": "invalid_url", "checks": []}
    try:
        status, _ = validate_staging_structure(url, schema="ct_app")
        if status != "ok":
            return {"status": "schema_mismatch", "checks": []}

        if len(CHECKS) != _EXPECTED_ID_COUNT or len({c[0] for c in CHECKS}) != len(CHECKS):
            return {"status": "failed", "checks": []}

        import psycopg
        findings = []
        with psycopg.connect(
            str(url).strip(), sslmode=sslmode_for(url),
            connect_timeout=8, autocommit=True,
        ) as conn:
            with conn.transaction():
                with conn.cursor() as cur:
                    cur.execute(
                        "SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY"
                    )
                    cur.execute("SET LOCAL statement_timeout = '20s'")
                    cur.execute("SET LOCAL lock_timeout = '3s'")
                    for machine_id, label, area, severity, query in CHECKS:
                        cur.execute(query)
                        result = cur.fetchone()
                        count = int(result[0])
                        if count < 0:
                            raise ValueError("Negative aggregate count")
                        findings.append({
                            "id": machine_id,
                            "area": area,
                            "label": label,
                            "severity": severity,
                            "count": count,
                        })
        return {
            "status": "issues_found" if any(x["count"] for x in findings) else "ok",
            "checks": findings,
        }
    except Exception:
        return {"status": "failed", "checks": []}
