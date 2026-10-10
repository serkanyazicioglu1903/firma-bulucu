"""Stage 7: isolated PostgreSQL procurement -> stock -> quality -> finance pilot.

ADMIN UI calls these functions only after explicit confirmation. This adapter
writes ONLY fixed, synthetic rows in ct_staging. It does not update the SQLite
operational app or accept arbitrary company data, SQL, or identifiers.
Every step commits atomically; an error rolls back that whole step.
"""
from datetime import date, timedelta
import secrets

from scripts.staging_validate import validate_staging_structure
from scripts.staging_transaction_smoke import validate_test_url

PREFIX = "CT_OPS7_"
ORDERED_KG = 1000
SHIPMENT_KG = 600
HOLD_KG = 100
TOTAL_EUR = 2250.0
PAYMENT_EUR = 500.0
MAX_ID = (1 << 62) - 1


class PilotSafetyError(Exception):
    """Safe internal signal; never echo PostgreSQL connection errors."""


def names(identifier):
    if type(identifier) is not int or not (-MAX_ID <= identifier <= -1000):
        raise PilotSafetyError("Invalid fictional record ID.")
    marker = PREFIX + str(-identifier)
    return {part: marker + "_" + part for part in
            ("PRODUCT", "WAREHOUSE", "SUPPLIER", "PO", "BANK", "QUALITY", "SHIPMENT")}


def _ready(url):
    if not validate_test_url(url):
        raise PilotSafetyError("Invalid test connection.")
    result, _ = validate_staging_structure(url)
    if result != "ok":
        raise PilotSafetyError("Schema must be verified before staging writes.")


def _connect(url):
    import psycopg
    return psycopg.connect(str(url).strip(), sslmode="require",
                           connect_timeout=8, autocommit=True)


def _settings(cur, *, read_only=False):
    if read_only:
        cur.execute("SET TRANSACTION READ ONLY")
    cur.execute("SET LOCAL statement_timeout='20s'")
    cur.execute("SET LOCAL lock_timeout='3s'")
    cur.execute('SET LOCAL search_path TO "ct_staging", pg_catalog')


def _one(cur, sql, params, label):
    cur.execute(sql, params)
    if cur.fetchone() is None:
        raise PilotSafetyError("Fictional " + label + " state did not match.")


def _guard(cur, identifier):
    """Lock and verify a complete, exactly marked synthetic parent set."""
    n = names(identifier)
    cur.execute(
        'SELECT po.quantity_kg,s.quantity_kg,s.received_to_stock,'
        'pa.amount,pa.paid_amount,a.balance '
        'FROM "ct_staging"."purchase_orders" po '
        'JOIN "ct_staging"."product_catalog" p ON p.id=po.product_id '
        'JOIN "ct_staging"."warehouses" w ON w.id=po.destination_warehouse_id '
        'JOIN "ct_staging"."shipments" s ON s.id=po.id AND s.purchase_order_id=po.id '
        'JOIN "ct_staging"."payables" pa ON pa.id=po.id AND pa.purchase_order_id=po.id '
        'JOIN "ct_staging"."cash_accounts" a ON a.id=po.id '
        'WHERE po.id=%s AND po.po_number=%s AND po.supplier=%s '
        'AND po.product_name=%s AND p.id=po.id AND p.name=%s '
        'AND w.id=po.id AND w.name=%s '
        'AND s.destination_warehouse_id=po.id AND s.shipment_ref=%s '
        'AND pa.supplier=%s AND a.name=%s '
        'FOR UPDATE OF po,s,pa,a',
        (identifier,n["PO"],n["SUPPLIER"],n["PRODUCT"],n["PRODUCT"],
         n["WAREHOUSE"],n["SHIPMENT"],n["SUPPLIER"],n["BANK"]),
    )
    result = cur.fetchone()
    if not result or result[0] != ORDERED_KG or result[1] != SHIPMENT_KG \
            or result[3] != TOTAL_EUR:
        raise PilotSafetyError("Selected record is not a complete fictional set.")
    return result


def list_ops_pilots(url):
    """Bounded read-only query; return only exact fictional relationships."""
    try:
        _ready(url)
        with _connect(url) as conn:
            with conn.transaction():
                with conn.cursor() as cur:
                    _settings(cur, read_only=True)
                    cur.execute(
                        'SELECT po.id, s.received_to_stock, '
                        'l.quantity_received_kg, l.quantity_available_kg, '
                        'l.quality_hold_kg, q.id, pa.amount, pa.paid_amount, '
                        'a.balance, ft.id '
                        'FROM "ct_staging"."purchase_orders" po '
                        'JOIN "ct_staging"."product_catalog" p ON p.id=po.id '
                        'JOIN "ct_staging"."warehouses" w ON w.id=po.id '
                        'JOIN "ct_staging"."shipments" s ON s.id=po.id '
                        'AND s.purchase_order_id=po.id '
                        'JOIN "ct_staging"."payables" pa ON pa.id=po.id '
                        'AND pa.purchase_order_id=po.id '
                        'JOIN "ct_staging"."cash_accounts" a ON a.id=po.id '
                        'LEFT JOIN "ct_staging"."inventory_lots" l ON l.id=po.id '
                        'AND l.shipment_id=s.id AND l.product_id=p.id '
                        'LEFT JOIN "ct_staging"."quality_cases" q ON q.id=po.id '
                        'AND q.inventory_lot_id=l.id '
                        'LEFT JOIN "ct_staging"."finance_transactions" ft '
                        'ON ft.id=po.id AND ft.payable_id=pa.id AND ft.account_id=a.id '
                        'WHERE po.id BETWEEN %s AND -1000 '
                        'AND po.po_number=%s || (-po.id)::text || %s '
                        'AND po.supplier=%s || (-po.id)::text || %s '
                        'AND po.product_name=p.name '
                        'AND p.name=%s || (-po.id)::text || %s '
                        'AND w.name=%s || (-po.id)::text || %s '
                        'AND a.name=%s || (-po.id)::text || %s '
                        'AND s.shipment_ref=%s || (-po.id)::text || %s '
                        'AND pa.supplier=po.supplier '
                        'ORDER BY po.id ASC LIMIT 50',
                        (-MAX_ID, PREFIX, "_PO", PREFIX, "_SUPPLIER",
                         PREFIX, "_PRODUCT", PREFIX, "_WAREHOUSE",
                         PREFIX, "_BANK", PREFIX, "_SHIPMENT"),
                    )
                    found = cur.fetchall()
        items=[]
        for ident, received, quantity, available, held, case_id, amount, paid, bank, tx_id in found:
            if type(ident) is not int or not (-MAX_ID <= ident <= -1000):
                continue
            received_kg = float(quantity or 0) if received else 0.0
            held_kg = float(held or 0) if case_id is not None else 0.0
            items.append({
                "id": ident,
                "stage": ("Ödeme" if tx_id is not None else
                          "Kalite HOLD" if case_id is not None else
                          "Mal kabul" if received else "Sipariş"),
                "ordered_kg": float(ORDERED_KG),
                "received_kg": received_kg,
                "hold_kg": held_kg,
                "available_kg": max(0.0,float(available or 0)-held_kg),
                "remaining_kg": float(ORDERED_KG)-received_kg,
                "payable_eur": float(amount)-float(paid),
                "bank_eur": float(bank),
            })
        return "ok", items
    except PilotSafetyError:
        return "not_ready", []
    except Exception:
        return "failed", []


def create_ops_pilot(url):
    """Create fictional supplier/PO/shipment/payable/bank rows atomically."""
    try:
        _ready(url)
        identifier = -(1000 + secrets.randbelow(1 << 50))
        n = names(identifier)
        due = (date.today()+timedelta(days=90)).isoformat()
        with _connect(url) as conn:
            with conn.transaction():
                with conn.cursor() as cur:
                    _settings(cur)
                    cur.execute(
                        'INSERT INTO "ct_staging"."product_catalog" (id,name,notes) '
                        'VALUES (%s,%s,%s)',
                        (identifier,n["PRODUCT"],"Fictional stage 7 sandbox"))
                    cur.execute(
                        'INSERT INTO "ct_staging"."warehouses" (id,name,notes) '
                        'VALUES (%s,%s,%s)',
                        (identifier,n["WAREHOUSE"],"Fictional stage 7 sandbox"))
                    cur.execute(
                        'INSERT INTO "ct_staging"."purchase_orders" '
                        '(id,po_number,supplier,product_id,product_name,quantity_kg,'
                        'unit_price,currency,destination_warehouse_id) '
                        'VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)',
                        (identifier,n["PO"],n["SUPPLIER"],identifier,n["PRODUCT"],
                         ORDERED_KG,2.25,"EUR",identifier))
                    cur.execute(
                        'INSERT INTO "ct_staging"."shipments" '
                        '(id,purchase_order_id,shipment_ref,quantity_kg,'
                        'destination_warehouse_id,received_to_stock) '
                        'VALUES (%s,%s,%s,%s,%s,%s)',
                        (identifier,identifier,n["SHIPMENT"],SHIPMENT_KG,identifier,0))
                    cur.execute(
                        'INSERT INTO "ct_staging"."payables" '
                        '(id,supplier,purchase_order_id,due_date,amount,'
                        'currency,paid_amount) VALUES (%s,%s,%s,%s,%s,%s,%s)',
                        (identifier,n["SUPPLIER"],identifier,due,TOTAL_EUR,"EUR",0))
                    cur.execute(
                        'INSERT INTO "ct_staging"."cash_accounts" '
                        '(id,name,currency,balance) VALUES (%s,%s,%s,%s)',
                        (identifier,n["BANK"],"EUR",10000.0))
        return "created", identifier
    except PilotSafetyError:
        return "not_ready", None
    except Exception:
        return "failed", None


def advance_ops_pilot(url, identifier, step):
    """Stage transitions with optimistic checks and transaction rollback."""
    if step not in ("receive", "hold", "pay"):
        return "not_ready"
    try:
        n=names(identifier)
        _ready(url)
        with _connect(url) as conn:
            with conn.transaction():
                with conn.cursor() as cur:
                    _settings(cur)
                    parent=_guard(cur, identifier)
                    if step == "receive":
                        if parent[2] != 0:
                            raise PilotSafetyError("Shipment was already received.")
                        _one(cur,
                             'UPDATE "ct_staging"."shipments" SET received_to_stock=1 '
                             'WHERE id=%s AND purchase_order_id=%s '
                             'AND received_to_stock=0 RETURNING id',
                             (identifier,identifier),"receipt")
                        cur.execute(
                            'INSERT INTO "ct_staging"."inventory_lots" '
                            '(id,product_id,product_name,warehouse_id,purchase_order_id,'
                            'shipment_id,quantity_received_kg,quantity_available_kg,'
                            'quality_hold_kg,quality_status,lot_number) '
                            'VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)',
                            (identifier,identifier,n["PRODUCT"],identifier,
                             identifier,identifier,SHIPMENT_KG,SHIPMENT_KG,0,
                             "Released",n["SHIPMENT"]))
                    elif step == "hold":
                        if parent[2] != 1:
                            raise PilotSafetyError("Receive first.")
                        _one(cur,
                             'UPDATE "ct_staging"."inventory_lots" '
                             'SET quality_hold_kg=%s,quality_status=%s '
                             'WHERE id=%s AND shipment_id=%s '
                             'AND quantity_available_kg=%s AND quality_hold_kg=0 '
                             'RETURNING id',
                             (HOLD_KG,"HOLD",identifier,identifier,SHIPMENT_KG),
                             "quality hold")
                        cur.execute(
                            'INSERT INTO "ct_staging"."quality_cases" '
                            '(id,case_no,opened_date,product_id,product_name,'
                            'inventory_lot_id,purchase_order_id,shipment_id,'
                            'affected_quantity_kg,description) '
                            'VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)',
                            (identifier,n["QUALITY"],date.today().isoformat(),
                             identifier,n["PRODUCT"],identifier,identifier,
                             identifier,HOLD_KG,"Fictional stage 7 quality HOLD"))
                    elif step == "pay":
                        if parent[2] != 1 or parent[4] != 0:
                            raise PilotSafetyError("Receive first or payment already posted.")
                        # Refuse settlement unless the exact synthetic HOLD remains intact.
                        _one(cur,
                             'SELECT id FROM "ct_staging"."inventory_lots" '
                             'WHERE id=%s AND shipment_id=%s AND product_id=%s '
                             'AND quantity_received_kg=%s AND quantity_available_kg=%s '
                             'AND quality_hold_kg=%s AND quality_status=%s '
                             'FOR UPDATE',
                             (identifier,identifier,identifier,SHIPMENT_KG,
                              SHIPMENT_KG,HOLD_KG,"HOLD"),"stock HOLD")
                        _one(cur,
                             'SELECT id FROM "ct_staging"."quality_cases" '
                             'WHERE id=%s AND case_no=%s '
                             'AND inventory_lot_id=%s FOR UPDATE',
                             (identifier,n["QUALITY"],identifier),"quality")
                        _one(cur,
                             'UPDATE "ct_staging"."payables" SET paid_amount=%s,'
                             'status=%s WHERE id=%s AND purchase_order_id=%s '
                             'AND paid_amount=0 AND amount=%s RETURNING id',
                             (PAYMENT_EUR,"Kısmi",identifier,identifier,TOTAL_EUR),
                             "supplier settlement")
                        _one(cur,
                             'UPDATE "ct_staging"."cash_accounts" '
                             'SET balance=balance-%s WHERE id=%s AND name=%s '
                             'AND balance>=%s RETURNING id',
                             (PAYMENT_EUR,identifier,n["BANK"],PAYMENT_EUR),
                             "cash movement")
                        cur.execute(
                            'INSERT INTO "ct_staging"."finance_transactions" '
                            '(id,transaction_type,payable_id,transaction_date,'
                            'amount,currency,account_id,reference) '
                            'VALUES (%s,%s,%s,%s,%s,%s,%s,%s)',
                            (identifier,"Ödeme",identifier,date.today().isoformat(),
                             PAYMENT_EUR,"EUR",identifier,n["PO"]))
        return "updated"
    except PilotSafetyError:
        return "not_ready"
    except Exception:
        return "failed"


def delete_ops_pilot(url, identifier):
    """Delete precisely one fully marked synthetic set, never general rows."""
    try:
        n=names(identifier)
        _ready(url)
        with _connect(url) as conn:
            with conn.transaction():
                with conn.cursor() as cur:
                    _settings(cur)
                    _guard(cur, identifier)
                    # Optional downstream records, then required parent records.
                    statements=[
                        ("finance_transactions",
                         'id=%s AND payable_id=%s AND account_id=%s '
                         'AND reference=%s',(identifier,identifier,identifier,n["PO"]),False),
                        ("quality_cases",
                         'id=%s AND case_no=%s AND inventory_lot_id=%s',
                         (identifier,n["QUALITY"],identifier),False),
                        ("inventory_lots",
                         'id=%s AND product_id=%s AND shipment_id=%s',
                         (identifier,identifier,identifier),False),
                        ("shipments",
                         'id=%s AND purchase_order_id=%s AND shipment_ref=%s',
                         (identifier,identifier,n["SHIPMENT"]),True),
                        ("payables",
                         'id=%s AND purchase_order_id=%s AND supplier=%s',
                         (identifier,identifier,n["SUPPLIER"]),True),
                        ("purchase_orders",
                         'id=%s AND po_number=%s AND supplier=%s',
                         (identifier,n["PO"],n["SUPPLIER"]),True),
                        ("cash_accounts",'id=%s AND name=%s',
                         (identifier,n["BANK"]),True),
                        ("warehouses",'id=%s AND name=%s',
                         (identifier,n["WAREHOUSE"]),True),
                        ("product_catalog",'id=%s AND name=%s',
                         (identifier,n["PRODUCT"]),True),
                    ]
                    for table, where, params, mandatory in statements:
                        # SQL identifiers/predicates are trusted hard-coded literals.
                        cur.execute('SELECT 1 FROM "ct_staging"."' + table +
                                    '" WHERE id=%s LIMIT 1',(identifier,))
                        exists=cur.fetchone() is not None
                        if exists:
                            cur.execute('DELETE FROM "ct_staging"."' + table +
                                        '" WHERE ' + where + ' RETURNING id', params)
                            if cur.fetchone() is None:
                                raise PilotSafetyError("Sandbox ownership mismatch.")
                        elif mandatory:
                            raise PilotSafetyError("Incomplete sandbox set.")
        return "deleted"
    except PilotSafetyError:
        return "not_ready"
    except Exception:
        return "failed"
