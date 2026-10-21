"""Signed-session -> dedicated LOGIN -> RLS -> atomic business transaction.

Disabled until a separately approved deployment configures runtime mode and
per-account credentials. Never uses legacy DATABASE_URL, SET ROLE, or an admin
connection. Credentials and database errors are never returned to callers.
"""
import hashlib
import json
import os
from urllib.parse import urlsplit, unquote
from uuid import UUID
from decimal import Decimal

from security_admin import _secret, current_user
from scripts.company_session_principal import verified_company_principal
from scripts.company_db_role_preflight import review_postgres_app_role_on_cursor, _ROLE, _DENIED_ROLES
from scripts.group_company_catalog import COMPANY_LABELS
from scripts.postgres_scoped_company_read import OWNED_READ_SECTIONS, read_company_records_on_cursor, authorize_company_on_cursor
from scripts.postgres_scoped_company_crm_read import CRM_READ_SECTIONS, read_company_crm_on_cursor
from scripts.postgres_company_executive_snapshot import company_executive_snapshot_on_cursor
from scripts.postgres_scoped_company_write_rehearsal import (
    _ACTIONS, _ACTION_TABLE, ScopedWriteDenied, _checked_text, _checked_id,
    _positive, _money, _calendar_date,
)
from scripts.postgres_scoped_company_crm_write_rehearsal import _CRM_HANDLERS, _CRM_ACTIONS

MODE_KEY = 'CT_COMPANY_RUNTIME_MODE'
READ_MODE = 'SIGNED_ROLE_READ_ONLY'
WRITE_MODE = 'SIGNED_ROLE_READ_WRITE'


def runtime_mode():
    values = [_secret(MODE_KEY, ''), os.environ.get(MODE_KEY, '')]
    if not all(isinstance(v, str) for v in values):
        return 'invalid'
    selected = [v for v in values if v]
    if not selected:
        return 'disabled'
    if len(set(selected)) != 1 or selected[0] not in (READ_MODE, WRITE_MODE):
        return 'invalid'
    return selected[0]


def _account_connection(principal):
    try:
        config = json.loads(_secret('CT_COMPANY_DB_CONNECTIONS_JSON', ''))
        if not isinstance(config, dict) or principal not in config:
            return None
        roles = []
        for name, item in config.items():
            if not isinstance(item, dict) or set(item) != {'role', 'url'}:
                return None
            role, url = item['role'], item['url']
            if not isinstance(role, str) or not _ROLE.fullmatch(role) or role in _DENIED_ROLES:
                return None
            parsed = urlsplit(url)
            if (parsed.scheme not in ('postgresql', 'postgres') or not parsed.hostname
                    or not parsed.password or parsed.fragment or parsed.query
                    or unquote(parsed.username or '').split('.')[0] != role):
                return None
            roles.append(role)
        if len(set(roles)) != len(roles):
            return None
        return config[principal]
    except (TypeError, ValueError, KeyError):
        return None


def _ssl(url):
    p = urlsplit(url)
    # Local test login roles need to exercise actual non-superuser connections.
    if (os.environ.get('CT_LOCAL_POSTGRES_TEST') == '1'
            and p.hostname in ('127.0.0.1', 'localhost') and p.port == 5432
            and p.path == '/ct_ci_control_tower'
            and (p.username or '').startswith('ct_ci_runtime_')
            and not p.query and not p.fragment):
        return 'disable'
    return 'require'


def _bind(cur, principal, role, app_role):
    report = review_postgres_app_role_on_cursor(cur, role)
    if not report['least_privilege_review']:
        raise ScopedWriteDenied('unsafe_database_role')
    registry = ['company_login_bindings','company_read_grants','company_write_grants',
                'legal_entities','company_warehouse_scope','company_operation_audit',
                'company_requests','product_catalog','audit_log','system_settings',
                'company_suppliers','company_stock_movements']
    cur.execute("SELECT COUNT(*) FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace WHERE n.nspname='ct_app' AND c.relname=ANY(%s) AND c.relrowsecurity AND c.relforcerowsecurity AND c.relowner<>(SELECT oid FROM pg_roles WHERE rolname=current_user)",(registry,))
    if cur.fetchone() != (len(registry),):
        raise ScopedWriteDenied('unsafe_database_role')
    cur.execute('SELECT principal_id,app_role FROM ct_app.company_login_bindings WHERE db_role=current_user AND enabled')
    if cur.fetchall() != [(principal, app_role)]:
        raise ScopedWriteDenied('identity_mismatch')


def create_warehouse(cur, company, *, name, city=''):
    cur.execute('INSERT INTO ct_app.warehouses (name,city,legal_entity_id) VALUES (%s,%s,%s) RETURNING id',
                (_checked_text(name), str(city).strip()[:100], company))
    ident = cur.fetchone()[0]
    cur.execute('INSERT INTO ct_app.company_warehouse_scope (warehouse_id,legal_entity_id) VALUES (%s,%s)', (ident, company))
    return ident


def create_product(cur, company, *, name, category=''):
    cur.execute('INSERT INTO ct_app.product_catalog (name,category) VALUES (%s,%s) RETURNING id',
                (_checked_text(name), str(category).strip()[:100]))
    return cur.fetchone()[0]


def create_account(cur, company, *, name, currency, opening_balance=0):
    value = Decimal(str(opening_balance))
    if not value.is_finite() or value < 0:
        raise ScopedWriteDenied('invalid_input')
    cur.execute('INSERT INTO ct_app.cash_accounts (name,currency,balance,legal_entity_id) VALUES (%s,%s,%s,%s) RETURNING id',
                (_checked_text(name), _money(currency), value, company))
    return cur.fetchone()[0]


def create_receivable(cur, company, *, customer_id, invoice_no, due_date, amount, currency):
    customer = _checked_id(customer_id)
    cur.execute('SELECT id FROM ct_app.customers WHERE id=%s AND legal_entity_id=%s', (customer, company))
    if cur.fetchone() is None:
        raise ScopedWriteDenied('wrong_company_customer')
    invoice = _checked_text(invoice_no)
    cur.execute('SELECT pg_advisory_xact_lock(4603,hashtext(%s))', (f'{company}|{customer}|{invoice}',))
    cur.execute('SELECT id FROM ct_app.receivables WHERE customer_id=%s AND invoice_no=%s AND legal_entity_id=%s', (customer, invoice, company))
    if cur.fetchone():
        raise ScopedWriteDenied('duplicate_invoice')
    cur.execute('INSERT INTO ct_app.receivables (customer_id,invoice_no,due_date,amount,currency,legal_entity_id) VALUES (%s,%s,%s,%s,%s,%s) RETURNING id',
                (customer, invoice, _calendar_date(due_date), _positive(amount), _money(currency), company))
    return cur.fetchone()[0]


def create_quote(cur, company, *, customer_id, product_name, **economics):
    from scripts.real_quote_estimator import calculate_real_quote
    customer = _checked_id(customer_id)
    cur.execute('SELECT id FROM ct_app.customers WHERE id=%s AND legal_entity_id=%s', (customer,company))
    if cur.fetchone() is None:
        raise ScopedWriteDenied('wrong_company_customer')
    cur.execute('SELECT code FROM ct_app.legal_entities WHERE id=%s', (company,))
    code = cur.fetchone()[0]
    calc = calculate_real_quote(company_code=code, **economics)
    # A zero selling price is valid for a preview, never for a persisted
    # commercial offer that can later be invoiced or dispatched.
    if calc['gross_sales_base'] is None:
        raise ScopedWriteDenied('sale_price_required')
    name = _checked_text(product_name)
    columns = ('customer_id','product_name','quantity_kg','base_currency','buy_price_per_kg','buy_currency','buy_fx_to_base','sell_price_per_kg','sell_currency','sell_fx_to_base','landed_cost_per_kg','finance_cost_per_kg','total_cost_per_kg','profit_per_kg','profit_total_base','margin_pct','required_sell_price','legal_entity_id','calculation_snapshot')
    values = (customer,name,calc['quantity_kg'],calc['base_currency'],calc['buy_price_per_kg'],calc['buy_currency'],calc['buy_fx_to_base'],economics['sell_price_per_kg'],calc['sell_currency'],economics['sell_fx_to_base'],calc['landed_per_kg_base'],calc['finance_per_kg_base'],calc['cost_per_kg_base'],calc['profit_per_kg_base'],calc['profit_base'],calc['margin_pct'],calc['required_sell_price'],company,json.dumps({'inputs':economics,'result':calc},default=str))
    cur.execute('INSERT INTO ct_app.quotes ('+','.join(columns)+') VALUES ('+','.join(['%s']*len(columns))+') RETURNING id',values)
    return cur.fetchone()[0]


def invoice_quote(cur, company, *, quote_id, invoice_no, due_date):
    cur.execute('SELECT customer_id,quantity_kg,sell_price_per_kg,sell_currency,status FROM ct_app.quotes WHERE id=%s AND legal_entity_id=%s FOR UPDATE',(_checked_id(quote_id),company))
    quote = cur.fetchone()
    if not quote or quote[4] != 'Taslak':
        raise ScopedWriteDenied('quote_unavailable')
    amount = _positive(quote[1]) * _positive(quote[2])
    ident = create_receivable(cur,company,customer_id=quote[0],invoice_no=invoice_no,due_date=due_date,amount=amount,currency=quote[3])
    cur.execute('UPDATE ct_app.receivables SET quote_id=%s WHERE id=%s AND legal_entity_id=%s',(quote_id,ident,company))
    cur.execute("UPDATE ct_app.quotes SET status='Faturalandı' WHERE id=%s AND legal_entity_id=%s",(quote_id,company))
    return ident


def purchase_from_quote(cur, company, *, quote_id, po_number, supplier, product_id, warehouse_id):
    cur.execute('SELECT product_name,quantity_kg,buy_price_per_kg,buy_currency FROM ct_app.quotes WHERE id=%s AND legal_entity_id=%s FOR SHARE',(_checked_id(quote_id),company))
    quote = cur.fetchone()
    if quote is None:
        raise ScopedWriteDenied('quote_unavailable')
    cur.execute('SELECT name FROM ct_app.product_catalog WHERE id=%s',(_checked_id(product_id),))
    if cur.fetchone() != (quote[0],):
        raise ScopedWriteDenied('product_mismatch')
    ident = _ACTIONS['create_purchase_order'](cur,company,po_number=po_number,supplier=supplier,product_id=product_id,warehouse_id=warehouse_id,quantity_kg=quote[1],unit_price=quote[2],currency=quote[3])
    cur.execute('UPDATE ct_app.purchase_orders SET source_quote_id=%s WHERE id=%s AND legal_entity_id=%s',(quote_id,ident,company))
    return ident


def create_supplier(cur, company, *, name, website='', email='', country='', evidence=''):
    from scripts.postgres_scoped_company_crm_write_rehearsal import _text
    name=_text(name,required=True)
    website=_text(website,limit=500)
    if website and urlsplit(website).scheme not in ('https','http'):
        raise ScopedWriteDenied('invalid_input')
    cur.execute('INSERT INTO ct_app.company_suppliers (legal_entity_id,name,website,email,country,evidence) VALUES (%s,%s,%s,%s,%s,%s) RETURNING id',(company,name,website,_text(email),_text(country),_text(evidence,limit=2000)))
    return cur.fetchone()[0]


def dispatch_sale(cur, company, *, quote_id, lot_id, quantity_kg, reference, dispatch_date):
    quote_id,lot_id=_checked_id(quote_id),_checked_id(lot_id)
    qty=_positive(quantity_kg)
    cur.execute('SELECT product_name,quantity_kg,status FROM ct_app.quotes WHERE id=%s AND legal_entity_id=%s FOR UPDATE',(quote_id,company))
    quote=cur.fetchone()
    if not quote or quote[2]!='Faturalandı':
        raise ScopedWriteDenied('invoice_required')
    cur.execute('SELECT product_name,quantity_available_kg,quantity_reserved_kg,quality_status,quality_hold_kg,expiry_date FROM ct_app.inventory_lots WHERE id=%s AND legal_entity_id=%s FOR UPDATE',(lot_id,company))
    lot=cur.fetchone()
    if not lot or lot[0]!=quote[0]:
        raise ScopedWriteDenied('wrong_company_lot')
    if lot[3] not in ('Released','',None) or Decimal(str(lot[4] or 0))>0:
        raise ScopedWriteDenied('quality_hold_blocks_dispatch')
    when=_calendar_date(dispatch_date)
    if lot[5] and _calendar_date(lot[5]) < when:
        raise ScopedWriteDenied('expired_lot')
    if qty > Decimal(str(lot[1] or 0))-Decimal(str(lot[2] or 0)):
        raise ScopedWriteDenied('insufficient_stock')
    cur.execute('SELECT COALESCE(SUM(quantity_kg),0) FROM ct_app.company_stock_movements WHERE quote_id=%s AND legal_entity_id=%s',(quote_id,company))
    if qty+cur.fetchone()[0] > quote[1]:
        raise ScopedWriteDenied('over_dispatch')
    cur.execute('INSERT INTO ct_app.company_stock_movements (legal_entity_id,lot_id,quote_id,quantity_kg,reference,dispatch_date) VALUES (%s,%s,%s,%s,%s,%s) RETURNING id',(company,lot_id,quote_id,qty,_checked_text(reference),when))
    ident=cur.fetchone()[0]
    cur.execute('UPDATE ct_app.inventory_lots SET quantity_available_kg=quantity_available_kg-%s WHERE id=%s AND legal_entity_id=%s',(qty,lot_id,company))
    return ident


HANDLERS = {**_ACTIONS, **_CRM_HANDLERS,
            'create_warehouse': create_warehouse, 'create_product': create_product,
            'create_account': create_account, 'create_receivable': create_receivable, 'create_quote': create_quote,
            'invoice_quote': invoice_quote, 'purchase_from_quote': purchase_from_quote,
            'create_supplier':create_supplier,'dispatch_sale':dispatch_sale}
TABLES = {**_ACTION_TABLE, **_CRM_ACTIONS, 'create_warehouse': 'warehouses',
          'create_product': 'product_catalog', 'create_account': 'cash_accounts',
          'create_receivable': 'receivables', 'create_quote':'quotes',
          'invoice_quote':'receivables', 'purchase_from_quote':'purchase_orders',
          'create_supplier':'company_suppliers','dispatch_sale':'company_stock_movements'}
EXTRA_READS = {
    'Tedarikçiler': ('company_suppliers',('id','name','website','email','country','evidence')),
    'Müşteri Sevkiyatları': ('company_stock_movements',('id','lot_id','quote_id','quantity_kg','reference','dispatch_date')),
    'Depolar': ('warehouses', ('id','name','city','active')),
    'Ürünler': ('product_catalog', ('id','name','category','active')),
    'Teklifler': ('quotes', ('id','customer_id','product_name','quantity_kg','total_cost_per_kg','sell_price_per_kg','sell_currency','margin_pct','status')),
}


def _write(cur, principal, company_code, app_role, operation, request_id, inputs):
    if app_role != 'ADMIN' or operation not in HANDLERS:
        raise ScopedWriteDenied('forbidden')
    request_id = str(UUID(request_id))
    payload = hashlib.sha256(json.dumps(inputs, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()).hexdigest()
    status, company = authorize_company_on_cursor(cur, principal, company_code)
    if status != 'ok':
        raise ScopedWriteDenied(status)
    cur.execute('SELECT can_write FROM ct_app.company_write_grants WHERE principal_id=%s AND legal_entity_id=%s', (principal, company))
    if cur.fetchone() != (True,):
        raise ScopedWriteDenied('forbidden')
    # Serializes retry double-taps before checking the durable request ledger.
    cur.execute('SELECT pg_advisory_xact_lock(4604,hashtext(%s))', (principal+'|'+request_id,))
    cur.execute('SELECT legal_entity_id,operation,payload_hash,record_id FROM ct_app.company_requests WHERE principal_id=%s AND request_id=%s', (principal, request_id))
    previous = cur.fetchone()
    if previous:
        if previous[:3] != (company, operation, payload):
            raise ScopedWriteDenied('request_conflict')
        return previous[3]
    ident = HANDLERS[operation](cur, company, **inputs)
    cur.execute('INSERT INTO ct_app.company_operation_audit (principal_id,legal_entity_id,operation,target_table,record_id) VALUES (%s,%s,%s,%s,%s)',
                (principal, company, operation, TABLES[operation], ident))
    cur.execute('INSERT INTO ct_app.company_requests (principal_id,legal_entity_id,request_id,operation,payload_hash,record_id) VALUES (%s,%s,%s,%s,%s,%s)',
                (principal, company, request_id, operation, payload, ident))
    return ident


def _read(cur, principal, company_code, section):
    if section == 'Yönetici Özeti':
        return company_executive_snapshot_on_cursor(cur, principal, company_code)
    if section in CRM_READ_SECTIONS:
        return read_company_crm_on_cursor(cur, principal, company_code, section)
    if section in OWNED_READ_SECTIONS:
        return read_company_records_on_cursor(cur, principal, company_code, section)
    if section not in EXTRA_READS:
        raise ScopedWriteDenied('forbidden')
    status, company = authorize_company_on_cursor(cur, principal, company_code)
    if status != 'ok':
        return status, []
    table, columns = EXTRA_READS[section]
    sql = 'SELECT ' + ','.join(columns) + ' FROM ct_app.' + table
    params = () if table == 'product_catalog' else (company,)
    if params:
        sql += ' WHERE legal_entity_id=%s'
    cur.execute(sql + ' ORDER BY id DESC LIMIT 100', params)
    return 'ok', [dict(zip(columns, row)) for row in cur.fetchall()]


def execute_request(session_state, company_code, *, section=None, operation=None, request_id=None, inputs=None):
    """Only public runtime API. Rechecks login and DB identity on every request."""
    mode = runtime_mode()
    if mode not in (READ_MODE, WRITE_MODE):
        return 'disabled', None
    principal = verified_company_principal(session_state)
    if not principal or not isinstance(company_code,str) or company_code not in COMPANY_LABELS:
        return 'forbidden', None
    if operation and mode != WRITE_MODE:
        return 'read_only', None
    account = _account_connection(principal)
    if not account:
        return 'connection_not_configured', None
    app_role = (current_user() or {}).get('role')
    if app_role not in ('ADMIN', 'VIEWER') or (operation and app_role != 'ADMIN'):
        return 'forbidden', None
    try:
        import psycopg
        with psycopg.connect(account['url'], sslmode=_ssl(account['url']), connect_timeout=8, autocommit=True) as conn:
            with conn.transaction():
                with conn.cursor() as cur:
                    if not operation:
                        cur.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY')
                    else:
                        cur.execute('SET TRANSACTION ISOLATION LEVEL SERIALIZABLE')
                    cur.execute("SET LOCAL statement_timeout='20s'")
                    cur.execute("SET LOCAL lock_timeout='3s'")
                    cur.execute('SET LOCAL search_path=ct_app,pg_catalog')
                    _bind(cur, principal, account['role'], app_role)
                    if operation:
                        result = _write(cur, principal, company_code, app_role, operation, request_id, inputs or {})
                    else:
                        return _read(cur, principal, company_code, section)
        return 'ok', result
    except ScopedWriteDenied as error:
        return error.code, None
    except (TypeError, ValueError):
        return 'invalid_input', None
    except Exception:
        return 'failed', None
