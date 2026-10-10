"""Read-only operational PostgreSQL adapter for the isolated ct_app schema.

Deliberately exposes only aggregate counts. This is the first backend read
path; the existing Streamlit CRM, stock, quality and finance screens remain
SQLite-backed until full transactional write and security parity is verified.
No SQL writes, source SQLite access, or credentials are exposed.
"""
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
            str(url).strip(), connect_timeout=8, sslmode="require",
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
