"""DISPOSABLE-CI-ONLY customer/contact creation for four legal entities.

No Streamlit form, production entrypoint, migration or customer backfill.
The only URL entrypoint *rejects all non-local/non-disposable PostgreSQL*.
Caller must provide a separately authenticated server principal and role.
A role string or selected company is NOT production authorization.

Both CRM tables must have verified nonnull legal owners and validated
composite parent/company FK, and PostgreSQL company read + write grants.
Customer/contacts and operation audit are committed or rolled back together.
"""
from scripts.group_company_catalog import COMPANY_LABELS
from scripts.postgres_connection import sslmode_for
from scripts.postgres_scoped_company_crm_read import (
    company_crm_structure_ready_on_cursor,
)
from scripts.postgres_scoped_company_read import PRINCIPAL_PATTERN
from scripts.postgres_scoped_company_write_rehearsal import (
    ScopedWriteDenied,
    _checked_id,
    _owner_and_writer,
    _valid_disposable_test_target,
)

# Begin with ADMIN-only customer onboarding. SALES grants and application
# role identity checks require a separately reviewed per-operation matrix.
_CRM_ACTIONS = {
    "create_customer": "customers",
    "create_contact": "contacts",
}
_CRM_ROLES = frozenset({"ADMIN"})


def _text(value, *, required=False, limit=250):
    if not isinstance(value, str):
        raise ScopedWriteDenied("invalid_input")
    cleaned = value.strip()
    if (len(cleaned) > limit or (required and not cleaned)
            or any(ord(char) < 32 or ord(char) == 127 for char in cleaned)):
        raise ScopedWriteDenied("invalid_input")
    return cleaned


def create_customer_on_cursor(cur, company_id, *, name, country="",
                              sector="", status="Potansiyel", owner="",
                              currency="EUR"):
    """Insert only company-owned CRM master in an independently guarded txn."""
    company_id = _checked_id(company_id)
    customer = _text(name, required=True)
    location = _text(country, limit=100)
    group = _text(sector, limit=150)
    state = _text(status, required=True, limit=50)
    contact_owner = _text(owner, limit=100)
    curcode = _text(currency, required=True, limit=3).upper()
    if curcode not in ("EUR", "USD", "GBP", "TRY"):
        raise ScopedWriteDenied("invalid_input")
    cur.execute(
        'INSERT INTO "ct_app"."customers" '
        '(name,country,sector,status,owner,currency,legal_entity_id) '
        'VALUES (%s,%s,%s,%s,%s,%s,%s) RETURNING id',
        (customer, location, group, state, contact_owner, curcode, company_id),
    )
    return int(cur.fetchone()[0])


def create_contact_on_cursor(cur, company_id, *, customer_id, name,
                             title="", department="", email="", phone=""):
    """Reject other-company customers even when caller knows their row ID."""
    company_id = _checked_id(company_id)
    customer_id = _checked_id(customer_id)
    person = _text(name, required=True)
    job = _text(title, limit=150)
    area = _text(department, limit=150)
    mailbox = _text(email, limit=250)
    telephone = _text(phone, limit=70)
    cur.execute(
        'SELECT id FROM "ct_app"."customers" '
        'WHERE id=%s AND legal_entity_id=%s FOR SHARE',
        (customer_id, company_id),
    )
    if cur.fetchone() is None:
        raise ScopedWriteDenied("wrong_company_customer")
    cur.execute(
        'INSERT INTO "ct_app"."contacts" '
        '(customer_id,name,title,department,email,phone,legal_entity_id) '
        'VALUES (%s,%s,%s,%s,%s,%s,%s) RETURNING id',
        (customer_id, person, job, area, mailbox, telephone, company_id),
    )
    return int(cur.fetchone()[0])


_CRM_HANDLERS = {
    "create_customer": create_customer_on_cursor,
    "create_contact": create_contact_on_cursor,
}


def run_company_crm_write_on_cursor(cur, principal_id, company_code,
                                    role, operation, **inputs):
    """CI-only transaction unit. The CALLER MUST enforce disposable CI.

    Database write/grant/ownership checks are repeated for each action.
    Never pass untrusted browser role labels directly or a production cursor.
    """
    if (not isinstance(principal_id, str)
            or not PRINCIPAL_PATTERN.fullmatch(principal_id)
            or not isinstance(company_code, str)
            or company_code not in COMPANY_LABELS
            or not isinstance(role, str) or role not in _CRM_ROLES
            or not isinstance(operation, str) or operation not in _CRM_ACTIONS):
        raise ScopedWriteDenied("forbidden")
    company_id = _owner_and_writer(cur, principal_id, company_code)
    if not company_crm_structure_ready_on_cursor(cur):
        raise ScopedWriteDenied("not_ready")
    ident = _CRM_HANDLERS[operation](cur, company_id, **inputs)
    cur.execute(
        'INSERT INTO "ct_app"."company_operation_audit" '
        '(principal_id,legal_entity_id,operation,target_table,record_id) '
        'VALUES (%s,%s,%s,%s,%s)',
        (principal_id, company_id, operation, _CRM_ACTIONS[operation], ident),
    )
    return ident


def run_company_crm_write_rehearsal(url, principal_id, company_code,
                                    role, operation, **inputs):
    """Only executable via checked, disposable local CI PostgreSQL."""
    if (not isinstance(principal_id, str)
            or not PRINCIPAL_PATTERN.fullmatch(principal_id)
            or not isinstance(company_code, str)
            or company_code not in COMPANY_LABELS
            or not isinstance(role, str) or role not in _CRM_ROLES
            or not isinstance(operation, str) or operation not in _CRM_ACTIONS):
        return "forbidden", None
    if not _valid_disposable_test_target(url):
        return "disabled", None
    try:
        import psycopg
        with psycopg.connect(
            url, sslmode=sslmode_for(url), connect_timeout=8, autocommit=True,
        ) as conn:
            with conn.transaction():
                with conn.cursor() as cur:
                    cur.execute("SET LOCAL statement_timeout = '20s'")
                    cur.execute("SET LOCAL lock_timeout = '3s'")
                    cur.execute('SET LOCAL search_path TO "ct_app", pg_catalog')
                    ident = run_company_crm_write_on_cursor(
                        cur, principal_id, company_code, role, operation,
                        **inputs,
                    )
        return "ok", ident
    except ScopedWriteDenied as error:
        return error.code, None
    except Exception:
        # Do not return SQL exceptions, SQL values, connection secrets etc.
        return "failed", None
