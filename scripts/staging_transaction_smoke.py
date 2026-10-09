"""Optional PostgreSQL ct_staging smoke test with guaranteed rollback.

The test is *never* run automatically. It uses isolated, fictional rows with
explicit negative IDs (no sequence increments), and leaves no business rows.
It does not test the Streamlit modules' full business rules or switch backends.
"""
import secrets
from urllib.parse import urlsplit

from scripts.staging_validate import validate_staging_structure


SCHEMA = "ct_staging"
VERIFIED_TABLES = (
    "customers",
    "product_catalog",
    "opportunities",
    "quotes",
    "tasks",
    "warehouses",
    "purchase_orders",
    "shipments",
    "inventory_lots",
    "receivables",
    "payables",
    "quality_cases",
)


class _IntentionalRollback(Exception):
    """Private control signal: rolls the whole test transaction back."""


def validate_test_url(url):
    if not url or not str(url).strip():
        return False
    try:
        parsed = urlsplit(str(url).strip())
        return parsed.scheme in ("postgresql", "postgres") and bool(parsed.hostname)
    except ValueError:
        return False


def run_transactional_staging_smoke(url):
    """Return ('passed'|'failed'|'schema_mismatch'|'invalid_url', modules).

    May temporarily write fictional rows to ct_staging. Regardless of success
    or failure, every SQL write is within a rollback-only transaction.
    Never returns sensitive exception text or the database URL.
    """
    if not validate_test_url(url):
        return "invalid_url", []

    # Fail closed: a name-only validation is insufficient before test writes.
    schema_status, _ = validate_staging_structure(url)
    if schema_status != "ok":
        return "schema_mismatch", []

    try:
        import psycopg

        test_id = -secrets.randbelow(1 << 60) - 1
        marker = "CT_STAGING_SMOKE_" + secrets.token_hex(12)
        with psycopg.connect(
            str(url).strip(), connect_timeout=8, sslmode="require", autocommit=True
        ) as conn:
            try:
                with conn.transaction():
                    with conn.cursor() as cur:
                        cur.execute("SET LOCAL statement_timeout = '20s'")
                        cur.execute("SET LOCAL lock_timeout = '3s'")
                        cur.execute('SET LOCAL search_path TO "ct_staging", pg_catalog')

                        # Customer, product, sales opportunity and quotation.
                        cur.execute(
                            'INSERT INTO "ct_staging"."customers" (id, name) VALUES (%s, %s)',
                            (test_id, marker + "_CUSTOMER"),
                        )
                        cur.execute(
                            'INSERT INTO "ct_staging"."product_catalog" (id, name) VALUES (%s, %s)',
                            (test_id, marker + "_PRODUCT"),
                        )
                        cur.execute(
                            'INSERT INTO "ct_staging"."opportunities" '
                            '(id, customer_id, product) VALUES (%s, %s, %s)',
                            (test_id, test_id, marker + "_PRODUCT"),
                        )
                        cur.execute(
                            'INSERT INTO "ct_staging"."quotes" '
                            '(id, customer_id, opportunity_id, product_name, quantity_kg, sell_price_per_kg) '
                            'VALUES (%s, %s, %s, %s, %s, %s)',
                            (test_id, test_id, test_id, marker + "_PRODUCT", 100.0, 4.5),
                        )
                        cur.execute(
                            'SELECT q.quantity_kg, c.name, o.product '
                            'FROM "ct_staging"."quotes" q '
                            'JOIN "ct_staging"."customers" c ON c.id = q.customer_id '
                            'JOIN "ct_staging"."opportunities" o ON o.id = q.opportunity_id '
                            'WHERE q.id = %s',
                            (test_id,),
                        )
                        quote = cur.fetchone()
                        if not quote or quote[0] != 100.0 or quote[1] != marker + "_CUSTOMER":
                            raise RuntimeError("quote/CRM join failed")

                        # Separate task exercises INSERT / UPDATE / SELECT / DELETE.
                        cur.execute(
                            'INSERT INTO "ct_staging"."tasks" (id, title) VALUES (%s, %s)',
                            (test_id, marker + "_TASK"),
                        )
                        cur.execute(
                            'UPDATE "ct_staging"."tasks" SET status = %s WHERE id = %s',
                            ("Tamamlandı", test_id),
                        )
                        cur.execute(
                            'SELECT status FROM "ct_staging"."tasks" WHERE id = %s',
                            (test_id,),
                        )
                        if cur.fetchone() != ("Tamamlandı",):
                            raise RuntimeError("task update/read failed")
                        cur.execute(
                            'DELETE FROM "ct_staging"."tasks" WHERE id = %s',
                            (test_id,),
                        )
                        cur.execute(
                            'SELECT id FROM "ct_staging"."tasks" WHERE id = %s',
                            (test_id,),
                        )
                        if cur.fetchone() is not None:
                            raise RuntimeError("task delete failed")

                        # Purchasing, receiving, stock and quality relationships.
                        cur.execute(
                            'INSERT INTO "ct_staging"."warehouses" (id, name) VALUES (%s, %s)',
                            (test_id, marker + "_WAREHOUSE"),
                        )
                        cur.execute(
                            'INSERT INTO "ct_staging"."purchase_orders" '
                            '(id, po_number, supplier, product_id, product_name, destination_warehouse_id) '
                            'VALUES (%s, %s, %s, %s, %s, %s)',
                            (test_id, marker + "_PO", marker + "_SUPPLIER", test_id,
                             marker + "_PRODUCT", test_id),
                        )
                        cur.execute(
                            'INSERT INTO "ct_staging"."shipments" '
                            '(id, purchase_order_id, quantity_kg, destination_warehouse_id) '
                            'VALUES (%s, %s, %s, %s)',
                            (test_id, test_id, 100.0, test_id),
                        )
                        cur.execute(
                            'INSERT INTO "ct_staging"."inventory_lots" '
                            '(id, product_id, product_name, warehouse_id, purchase_order_id, '
                            'shipment_id, quantity_received_kg, quantity_available_kg) '
                            'VALUES (%s, %s, %s, %s, %s, %s, %s, %s)',
                            (test_id, test_id, marker + "_PRODUCT", test_id, test_id,
                             test_id, 100.0, 100.0),
                        )
                        cur.execute(
                            'UPDATE "ct_staging"."inventory_lots" '
                            'SET quantity_available_kg = %s WHERE id = %s',
                            (75.0, test_id),
                        )
                        cur.execute(
                            'SELECT l.quantity_available_kg, s.quantity_kg '
                            'FROM "ct_staging"."inventory_lots" l '
                            'JOIN "ct_staging"."shipments" s ON s.id = l.shipment_id '
                            'WHERE l.id = %s',
                            (test_id,),
                        )
                        if cur.fetchone() != (75.0, 100.0):
                            raise RuntimeError("stock receipt/update failed")
                        cur.execute(
                            'INSERT INTO "ct_staging"."quality_cases" '
                            '(id, case_no, opened_date, customer_id, product_id, '
                            'product_name, inventory_lot_id, purchase_order_id, '
                            'shipment_id, description) '
                            'VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)',
                            (test_id, marker + "_QUALITY", "2026-01-01", test_id,
                             test_id, marker + "_PRODUCT", test_id, test_id,
                             test_id, "Fictional isolated rollback test"),
                        )

                        # Finance relationships, with no real balances affected.
                        cur.execute(
                            'INSERT INTO "ct_staging"."receivables" '
                            '(id, customer_id, due_date, amount) VALUES (%s, %s, %s, %s)',
                            (test_id, test_id, "2026-01-31", 450.0),
                        )
                        cur.execute(
                            'INSERT INTO "ct_staging"."payables" '
                            '(id, supplier, purchase_order_id, due_date, amount) '
                            'VALUES (%s, %s, %s, %s, %s)',
                            (test_id, marker + "_SUPPLIER", test_id, "2026-01-31", 320.0),
                        )
                        cur.execute(
                            'SELECT r.amount, p.amount FROM "ct_staging"."receivables" r '
                            'CROSS JOIN "ct_staging"."payables" p '
                            'WHERE r.id = %s AND p.id = %s',
                            (test_id, test_id),
                        )
                        if cur.fetchone() != (450.0, 320.0):
                            raise RuntimeError("finance read failed")

                    # Never commit test rows, including on success.
                    raise _IntentionalRollback()
            except _IntentionalRollback:
                pass

            # Confirm test rows are truly absent after the forced rollback.
            with conn.cursor() as cur:
                cur.execute("SET statement_timeout = '10000ms'")
                for table in VERIFIED_TABLES:
                    # Table names are fixed trusted literals, never user input.
                    cur.execute(
                        'SELECT 1 FROM "ct_staging"."' + table + '" WHERE id = %s LIMIT 1',
                        (test_id,),
                    )
                    if cur.fetchone() is not None:
                        return "failed", []
        return "passed", ["CRM", "Ürün", "Teklif", "Görev", "Satın alma",
                          "Sevkiyat", "Stok", "Kalite", "Finans"]
    except Exception:
        # Never surface raw psycopg exceptions or connection information.
        return "failed", []
