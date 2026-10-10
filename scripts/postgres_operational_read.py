"""Read-only operational PostgreSQL adapter for the isolated ct_app schema.

Deliberately exposes only aggregate counts. This is the first backend read
path; the existing Streamlit CRM, stock, quality and finance screens remain
SQLite-backed until full transactional write and security parity is verified.
No SQL writes, source SQLite access, or credentials are exposed.
"""
from scripts.postgres_connection import sslmode_for
from scripts.staging_transaction_smoke import validate_test_url
from scripts.staging_validate import validate_staging_structure

SCHEMA = "ct_app"
TABLES = (
    "customers", "product_catalog", "opportunities", "tasks", "purchase_orders",
    "shipments", "inventory_lots", "quality_cases", "receivables", "payables",
    "finance_transactions",
)


def read_operational_counts(url):
    """Return (status, safe counts).

    status: invalid_url | schema_mismatch | failed | ok.
    Existing ct_app tables are read in one read-only transaction.
    """
    if not validate_test_url(url):
        return "invalid_url", {}
    try:
        status, _ = validate_staging_structure(url, schema=SCHEMA)
        if status != "ok":
            return "schema_mismatch", {}
        import psycopg
        from psycopg import sql
        counts = {}
        with psycopg.connect(
            str(url).strip(), connect_timeout=8, sslmode=sslmode_for(url),
        ) as connection:
            with connection.cursor() as cur:
                cur.execute("SET TRANSACTION READ ONLY")
                cur.execute("SET LOCAL statement_timeout = '15s'")
                cur.execute("SET LOCAL lock_timeout = '3s'")
                for table in TABLES:
                    # Identifiers are fixed constants; never interpolate input.
                    cur.execute(sql.SQL("SELECT COUNT(*) FROM {}").format(
                        sql.Identifier(SCHEMA, table)
                    ))
                    counts[table] = int(cur.fetchone()[0])
        return "ok", counts
    except Exception:
        # Database exceptions may include secret URI details.
        return "failed", {}


# Reviewed server-side SQL. Do not accept arbitrary table names or SQL from UI.
# Avoid selecting sensitive notes/contact details until permissions are audited.
WORKSPACE_QUERIES = {
    "Müşteriler": (
        'SELECT id,name,country,sector,status,owner '
        'FROM "ct_app"."customers" ORDER BY id DESC LIMIT 100'
    ),
    "Ürün Kataloğu": (
        'SELECT id,name,category,supplier,active '
        'FROM "ct_app"."product_catalog" ORDER BY id DESC LIMIT 100'
    ),
    "Satın Alma": (
        'SELECT id,po_number,supplier,product_name,quantity_kg,unit_price,'
        'currency,status FROM "ct_app"."purchase_orders" ORDER BY id DESC LIMIT 100'
    ),
    "Sevkiyat": (
        'SELECT id,shipment_ref,purchase_order_id,quantity_kg,status,'
        'received_to_stock FROM "ct_app"."shipments" ORDER BY id DESC LIMIT 100'
    ),
    "Stok": (
        'SELECT id,product_name,lot_number,quantity_available_kg,'
        'quantity_reserved_kg,quality_status,quality_hold_kg '
        'FROM "ct_app"."inventory_lots" ORDER BY id DESC LIMIT 100'
    ),
    "Kalite": (
        'SELECT id,case_no,product_name,status,affected_quantity_kg,'
        'estimated_loss,currency FROM "ct_app"."quality_cases" ORDER BY id DESC LIMIT 100'
    ),
    "Alacaklar": (
        'SELECT id,customer_id,amount,paid_amount,currency,status '
        'FROM "ct_app"."receivables" ORDER BY id DESC LIMIT 100'
    ),
    "Borçlar": (
        'SELECT id,supplier,invoice_no,amount,paid_amount,currency,status '
        'FROM "ct_app"."payables" ORDER BY id DESC LIMIT 100'
    ),
    "Banka / Kasa": (
        'SELECT id,name,currency,balance,active '
        'FROM "ct_app"."cash_accounts" ORDER BY id DESC LIMIT 100'
    ),
    "Finans Hareketleri": (
        'SELECT id,transaction_type,transaction_date,amount,currency,reference '
        'FROM "ct_app"."finance_transactions" ORDER BY id DESC LIMIT 100'
    ),
}


def read_operational_workspace(url, workspace):
    """One audited SQL query under read-only transaction; no SQLite reads/writes.

    Caller must enforce ADMIN authentication before displaying any records.
    Returns (status, rows): ok | invalid_workspace | invalid_url |
    schema_mismatch | failed. DB credentials and errors are never returned.
    """
    if workspace not in WORKSPACE_QUERIES:
        return "invalid_workspace", []
    if not validate_test_url(url):
        return "invalid_url", []
    try:
        status, _ = validate_staging_structure(url, schema=SCHEMA)
        if status != "ok":
            return "schema_mismatch", []
        import psycopg
        from psycopg.rows import dict_row
        with psycopg.connect(
            str(url).strip(), connect_timeout=8, sslmode=sslmode_for(url),
            row_factory=dict_row,
        ) as connection:
            with connection.cursor() as cur:
                cur.execute("SET TRANSACTION READ ONLY")
                cur.execute("SET LOCAL statement_timeout = '15s'")
                cur.execute("SET LOCAL lock_timeout = '3s'")
                cur.execute(WORKSPACE_QUERIES[workspace])
                rows = cur.fetchall()
        return "ok", [dict(row) for row in rows]
    except Exception:
        return "failed", []
