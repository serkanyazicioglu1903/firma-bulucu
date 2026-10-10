"""Explicit, rollback-only end-to-end acceptance for the isolated ct_staging schema.

Never switches the app backend, moves real data, or creates lasting records.
The caller must acknowledge the test writes to staging; every helper carries
out its own database transaction and rolls back its fictional test rows.
No URL, connection error, or row-level business data appears in results.
"""
from scripts.staging_validate import validate_staging_structure
from scripts.staging_transaction_smoke import (
    run_transactional_staging_smoke,
    validate_test_url,
)
from scripts.staging_business_pilot import run_staging_business_pilot

ACKNOWLEDGEMENT = "ISOLATED_ROLLBACK_ONLY"


def run_staging_acceptance(url, acknowledgement=""):
    """Return a minimal, safe status record; never throw connection details.

    status: confirmation_required | invalid_url | schema_failed |
            transaction_failed | business_failed | passed
    completed: names of successful steps (no business records or credentials).
    """
    completed = []
    if acknowledgement != ACKNOWLEDGEMENT:
        return {"status": "confirmation_required", "completed": completed}
    if not validate_test_url(url):
        return {"status": "invalid_url", "completed": completed}
    try:
        schema_status, _issues = validate_staging_structure(url)
        if schema_status != "ok":
            return {"status": "schema_failed", "completed": completed}
        completed.append("schema")

        smoke_status, _tables = run_transactional_staging_smoke(url)
        if smoke_status != "passed":
            return {"status": "transaction_failed", "completed": completed}
        completed.append("rollback_crud")

        business_status, _summary = run_staging_business_pilot(url)
        if business_status != "passed":
            return {"status": "business_failed", "completed": completed}
        completed.append("rollback_business")
    except Exception:
        # Psycopg messages can contain connection details. Fail closed.
        return {"status": "failed", "completed": completed}
    return {"status": "passed", "completed": completed}
