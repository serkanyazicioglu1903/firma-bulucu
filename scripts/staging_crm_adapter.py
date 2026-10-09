"""Isolated *persistent fictional* PostgreSQL CRM pilot.

Unlike the rollback smoke tests, this is a first real, opt-in Streamlit CRM
adapter. It commits ONLY marked fictional customer/product/opportunity/task
rows to the ct_staging schema. These rows can be read after an app restart,
updated, and explicitly deleted. Production screens remain SQLite-backed.

Never enter real company data into this sandbox.
"""
import secrets

from scripts.staging_validate import validate_staging_structure
from scripts.staging_transaction_smoke import validate_test_url

SCHEMA = "ct_staging"
PREFIX = "CT_SANDBOX_"
MAX_ID = (1 << 62) - 1
SELECT_DEMOS = (
    'SELECT c.id, c.name, p.name, o.stage, t.status '
    'FROM "ct_staging"."customers" c '
    'JOIN "ct_staging"."product_catalog" p ON p.id = c.id '
    'JOIN "ct_staging"."opportunities" o ON o.id = c.id AND o.customer_id = c.id '
    'JOIN "ct_staging"."tasks" t ON t.id = c.id '
    'WHERE c.id < 0 '
    'AND c.name = %s || (-c.id)::text || %s '
    'AND p.name = %s || (-c.id)::text || %s '
    'AND o.product = p.name '
    'AND t.title = %s || (-c.id)::text || %s '
    'ORDER BY c.id ASC LIMIT 50'
)


class SandboxError(Exception):
    """Never expose a raw PostgreSQL or connection error to the UI."""


def _marker(identifier):
    if type(identifier) is not int or not (-MAX_ID <= identifier <= -1000):
        raise SandboxError("Invalid sandbox ID")
    return PREFIX + str(-identifier)


def _names(identifier):
    marker = _marker(identifier)
    return marker + "_CUSTOMER", marker + "_PRODUCT", marker + "_TASK"


def _ready(url):
    if not validate_test_url(url):
        raise SandboxError("Missing or invalid isolated PostgreSQL URL")
    status, _issues = validate_staging_structure(url)
    if status != "ok":
        raise SandboxError("PostgreSQL test schema not ready")


def _connect(url):
    import psycopg
    return psycopg.connect(str(url).strip(), connect_timeout=8,
                           sslmode="require", autocommit=True)


def _limit(cur):
    cur.execute("SET LOCAL statement_timeout = '15s'")
    cur.execute("SET LOCAL lock_timeout = '3s'")
    cur.execute('SET LOCAL search_path TO "ct_staging", pg_catalog')


def list_sandbox_crm(url):
    """Read only the four mutually matched fictional records; no real rows."""
    try:
        _ready(url)
        with _connect(url) as conn:
            with conn.transaction():
                with conn.cursor() as cur:
                    cur.execute("SET TRANSACTION READ ONLY")
                    _limit(cur)
                    cur.execute(SELECT_DEMOS,
                                (PREFIX, "_CUSTOMER", PREFIX, "_PRODUCT",
                                 PREFIX, "_TASK"))
                    rows = cur.fetchall()
        demos = []
        for ident, customer, product, stage, task in rows:
            # Defense in depth against prefix collisions or unrelated rows.
            if isinstance(ident, int) and -MAX_ID <= ident <= -1000:
                # The task/status column is intentionally a status, not title.
                expected_customer, expected_product, _ = _names(ident)
                if customer == expected_customer and product == expected_product:
                    demos.append({"id": ident, "customer": customer,
                                  "product": product, "stage": stage,
                                  "task_status": task})
        return "ok", demos
    except SandboxError:
        return "not_ready", []
    except Exception:
        return "failed", []


def create_sandbox_crm(url):
    """Commit one fictional CRM set only after the UI's explicit admin action."""
    try:
        _ready(url)
        ident = -(secrets.randbelow(1 << 50) + 1000)
        customer, product, title = _names(ident)
        with _connect(url) as conn:
            with conn.transaction():
                with conn.cursor() as cur:
                    _limit(cur)
                    cur.execute('INSERT INTO "ct_staging"."customers" '
                                '(id,name,notes) VALUES (%s,%s,%s)',
                                (ident,customer,"Fictional PostgreSQL CRM sandbox"))
                    cur.execute('INSERT INTO "ct_staging"."product_catalog" '
                                '(id,name,notes) VALUES (%s,%s,%s)',
                                (ident,product,"Fictional PostgreSQL CRM sandbox"))
                    cur.execute('INSERT INTO "ct_staging"."opportunities" '
                                '(id,customer_id,product,stage,owner) '
                                'VALUES (%s,%s,%s,%s,%s)',
                                (ident,ident,product,"Lead","SANDBOX"))
                    cur.execute('INSERT INTO "ct_staging"."tasks" '
                                '(id,title,status) VALUES (%s,%s,%s)',
                                (ident,title,"Açık"))
        return "created", ident
    except SandboxError:
        return "not_ready", None
    except Exception:
        return "failed", None


def update_sandbox_crm(url, identifier):
    """Update only the selected fictional opportunity + task atomically."""
    try:
        customer, product, title = _names(identifier)
        _ready(url)
        with _connect(url) as conn:
            with conn.transaction():
                with conn.cursor() as cur:
                    _limit(cur)
                    cur.execute('SELECT id FROM "ct_staging"."customers" '
                                'WHERE id=%s AND name=%s FOR UPDATE',
                                (identifier,customer))
                    if cur.fetchone() is None:
                        raise SandboxError("Not an approved sandbox record")
                    cur.execute('UPDATE "ct_staging"."opportunities" SET stage=%s '
                                'WHERE id=%s AND customer_id=%s AND product=%s '
                                'AND stage=%s',
                                ("Numune", identifier, identifier, product, "Lead"))
                    changed = cur.rowcount
                    if changed != 1:
                        raise SandboxError("Sandbox opportunity not in Lead stage")
                    cur.execute('UPDATE "ct_staging"."tasks" SET status=%s '
                                'WHERE id=%s AND title=%s AND status=%s',
                                ("Tamamlandı", identifier, title, "Açık"))
                    if cur.rowcount != 1:
                        raise SandboxError("Sandbox task not in Open state")
        return "updated"
    except SandboxError:
        return "not_ready"
    except Exception:
        return "failed"


def delete_sandbox_crm(url, identifier):
    """Delete one exactly marked fictional set; never clear other staging rows."""
    try:
        customer, product, title = _names(identifier)
        _ready(url)
        with _connect(url) as conn:
            with conn.transaction():
                with conn.cursor() as cur:
                    _limit(cur)
                    cur.execute('SELECT id FROM "ct_staging"."customers" '
                                'WHERE id=%s AND name=%s FOR UPDATE',
                                (identifier,customer))
                    if cur.fetchone() is None:
                        raise SandboxError("Not an approved sandbox record")
                    # Dependents before parents; FK failures roll back the set.
                    for table, predicate, parameters in (
                        ("tasks", "id=%s AND title=%s", (identifier,title)),
                        ("opportunities", "id=%s AND customer_id=%s AND product=%s",
                         (identifier,identifier,product)),
                        ("customers", "id=%s AND name=%s", (identifier,customer)),
                        ("product_catalog", "id=%s AND name=%s", (identifier,product)),
                    ):
                        # Trusted literal table and predicate, no user SQL.
                        cur.execute('DELETE FROM "ct_staging"."' + table + '" WHERE '
                                    + predicate, parameters)
                        if cur.rowcount != 1:
                            raise SandboxError("Sandbox set is not complete")
        return "deleted"
    except SandboxError:
        return "not_ready"
    except Exception:
        return "failed"
