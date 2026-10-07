import argparse
import tempfile
from pathlib import Path

import control_tower as ct


REQUIRED_TABLES = {
    "customers", "contacts", "opportunities", "activities", "tasks",
    "product_catalog", "customer_product_status", "quotes",
    "purchase_orders", "shipments", "inventory_lots", "inventory_policy",
    "warehouses", "cash_accounts", "receivables", "payables",
    "finance_transactions", "cash_events", "quality_cases",
    "compliance_documents", "regulatory_items",
}


def scalar(sql, params=()):
    df = ct.query_df(sql, params)
    if df.empty:
        return 0
    return int(df.iloc[0, 0] or 0)


def run_checks():
    failures = []

    tables = set(
        ct.query_df(
            "SELECT name FROM sqlite_master WHERE type='table'"
        )["name"].tolist()
    )
    missing = sorted(REQUIRED_TABLES - tables)
    if missing:
        failures.append("Eksik tablolar: " + ", ".join(missing))

    checks = [
        (
            "Negatif stok miktarı",
            """SELECT COUNT(*) FROM inventory_lots
               WHERE COALESCE(quantity_available_kg,0)<0
                  OR COALESCE(quantity_reserved_kg,0)<0""",
        ),
        (
            "Rezervasyon mevcut stoktan büyük",
            """SELECT COUNT(*) FROM inventory_lots
               WHERE COALESCE(quantity_reserved_kg,0)
                   > COALESCE(quantity_available_kg,0) + 0.0001""",
        ),
        (
            "Kalite HOLD mevcut stoktan büyük",
            """SELECT COUNT(*) FROM inventory_lots
               WHERE COALESCE(quality_hold_kg,0)
                   > COALESCE(quantity_available_kg,0) + 0.0001""",
        ),
        (
            "Fazla tahsil edilmiş alacak",
            """SELECT COUNT(*) FROM receivables
               WHERE COALESCE(paid_amount,0) > COALESCE(amount,0) + 0.0001""",
        ),
        (
            "Fazla ödenmiş borç",
            """SELECT COUNT(*) FROM payables
               WHERE COALESCE(paid_amount,0) > COALESCE(amount,0) + 0.0001""",
        ),
        (
            "Müşterisiz satış fırsatı",
            """SELECT COUNT(*) FROM opportunities o
               LEFT JOIN customers c ON c.id=o.customer_id
               WHERE c.id IS NULL""",
        ),
        (
            "Aktif fırsatta geçersiz olasılık",
            """SELECT COUNT(*) FROM opportunities
               WHERE probability < 0 OR probability > 100""",
        ),
        (
            "Negatif finans hesabı kaydı",
            """SELECT COUNT(*) FROM cash_accounts
               WHERE balance IS NULL""",
        ),
    ]

    for label, sql in checks:
        count = scalar(sql)
        if count:
            failures.append(f"{label}: {count} kayıt")

    return failures


def main():
    parser = argparse.ArgumentParser(description="AS Control Tower preflight")
    parser.add_argument(
        "--demo",
        action="store_true",
        help="Geçici demo veritabanı oluşturup kontrol eder.",
    )
    args = parser.parse_args()

    previous = ct.DB_PATH
    temp = None
    try:
        if args.demo:
            temp = tempfile.TemporaryDirectory()
            ct.DB_PATH = Path(temp.name) / "preflight.db"
            ct.init_db()
            ct.seed_once()
            ct.seed_product_catalog()
            ct.seed_warehouses()
        else:
            ct.init_db()

        failures = run_checks()
        if failures:
            print("PRE-FLIGHT: FAIL")
            for item in failures:
                print(" -", item)
            raise SystemExit(1)

        print("PRE-FLIGHT: PASS")
        print("Şema ve temel veri bütünlüğü kontrolleri temiz.")
    finally:
        ct.DB_PATH = previous
        if temp:
            temp.cleanup()


if __name__ == "__main__":
    main()
