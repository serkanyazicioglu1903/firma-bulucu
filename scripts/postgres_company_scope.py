"""Read-only legal-entity separation review for AS Control Tower.

AS Ileri Gida and AS Food Global are separate legal entities. Before posting
real POs, stock, invoices or cash movements for both, an operator must review
which entity owns each record. This conservative structural indicator NEVER
certifies isolation: an indirect relationship may exist, and a column alone
does not establish row permissions or accounting correctness.

No company names, amounts, row values, credentials or data writes are returned.
"""
from scripts.postgres_connection import sslmode_for
from scripts.staging_transaction_smoke import validate_test_url
from scripts.staging_validate import validate_staging_structure

# Fixed application-schema tables that require an unambiguous legal owner.
CRITICAL_TABLES = (
    "purchase_orders",
    "shipments",
    "inventory_lots",
    "quality_cases",
    "payables",
    "receivables",
    "finance_transactions",
    "cash_accounts",
)
ENTITY_COLUMNS = ("company_id", "legal_entity_id", "owning_company_id")


def summarize_entity_columns(pairs):
    """Aggregate schema metadata only; do not infer ownership from company names.

    Return statuses for structural REVIEW, never 'approved'. Indirect ownership
    via a parent table must be evaluated by finance and engineering separately.
    """
    observed = set()
    for table, column in pairs:
        if table not in CRITICAL_TABLES or column not in ENTITY_COLUMNS:
            raise ValueError("unexpected_metadata")
        observed.add(table)
    missing = tuple(table for table in CRITICAL_TABLES if table not in observed)
    found = tuple(table for table in CRITICAL_TABLES if table in observed)
    return {
        "status": "review_required",
        "checked_count": len(CRITICAL_TABLES),
        "without_direct_entity": missing,
        "with_direct_entity": found,
        "isolation_verified": False,
    }


def assess_company_scope(url):
    """Read only pg metadata; reject malformed URLs or inaccessible databases."""
    empty = {
        "status": "failed",
        "checked_count": 0,
        "without_direct_entity": (),
        "with_direct_entity": (),
        "isolation_verified": False,
    }
    if not validate_test_url(url):
        return empty
    try:
        status, _ = validate_staging_structure(url, schema="ct_app")
        if status != "ok":
            return empty
        import psycopg

        with psycopg.connect(
            str(url).strip(), connect_timeout=8, sslmode=sslmode_for(url),
            autocommit=True,
        ) as conn:
            with conn.transaction():
                with conn.cursor() as cur:
                    cur.execute("SET TRANSACTION READ ONLY")
                    cur.execute("SET LOCAL statement_timeout = '15s'")
                    cur.execute("SET LOCAL lock_timeout = '3s'")
                    cur.execute(
                        "SELECT table_name,column_name "
                        "FROM information_schema.columns "
                        "WHERE table_schema='ct_app' "
                        "AND table_name = ANY(%s) "
                        "AND column_name = ANY(%s)",
                        (list(CRITICAL_TABLES), list(ENTITY_COLUMNS)),
                    )
                    return summarize_entity_columns(cur.fetchall())
    except Exception:
        # Errors may contain database credentials or private server details.
        return empty
