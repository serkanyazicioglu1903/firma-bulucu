"""Production-intended transactional PostgreSQL business operations for ct_app.

NOT wired to the existing SQLite Streamlit screens. The module is deliberately
inert until the application uses its functions under authenticated server-side
roles. Each operation validates the full ct_app schema and commits *one* atomic
transaction; unexpected errors are sanitized and rolled back.

Writes are disabled by default (AS_CONTROL_TOWER_PG_WRITES_ENABLED != 1).\nThe Streamlit app must not expose these write functions to customers until
security, backup/restore, real-database integration and feature-parity testing
are complete. ct_staging is never touched by this module.
"""
from datetime import date
import os
from decimal import Decimal, InvalidOperation

from scripts.postgres_connection import sslmode_for
from scripts.staging_transaction_smoke import validate_test_url
from scripts.staging_validate import validate_staging_structure

SCHEMA = "ct_app"

_ALLOWED_ROLES = {
    "create_customer": frozenset(("ADMIN", "SALES")),
    "create_product": frozenset(("ADMIN", "PURCHASING")),
    "create_purchase_order": frozenset(("ADMIN", "PURCHASING")),
    "create_shipment": frozenset(("ADMIN", "PURCHASING")),
    "receive_shipment": frozenset(("ADMIN", "PURCHASING")),
    "hold_inventory_lot": frozenset(("ADMIN", "QUALITY")),
    "create_payable": frozenset(("ADMIN", "FINANCE")),
    "pay_supplier": frozenset(("ADMIN", "FINANCE")),
}


class OperationRejected(ValueError):
    """A known validation failure with a safe public code."""

    def __init__(self, code):
        super().__init__(code)
        self.code = code


def _text(value, *, label="invalid_text", max_length=250):
    result = str(value or "").strip()
    if not result or len(result) > max_length:
        raise OperationRejected(label)
    return result


def _id(value):
    if type(value) is not int or value <= 0:
        raise OperationRejected("invalid_id")
    return value


def _positive(value):
    try:
        result = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        raise OperationRejected("invalid_amount") from None
    if not result.is_finite() or result <= 0:
        raise OperationRejected("invalid_amount")
    return result


def _date(value):
    value = _text(value, label="invalid_date", max_length=10)
    try:
        return date.fromisoformat(value).isoformat()
    except ValueError:
        raise OperationRejected("invalid_date") from None


def _currency(value):
    currency = _text(value, label="invalid_currency", max_length=3).upper()
    if currency not in ("EUR", "USD", "GBP", "TRY"):
        raise OperationRejected("invalid_currency")
    return currency


def _execute(url, role, operation, action):
    """Fail closed on schema/role/config errors; do not leak DB exceptions."""
    if role not in _ALLOWED_ROLES[operation]:
        return "forbidden", None
    # Preparation-only by default; full cutover requires explicit opt-in.
    if os.environ.get("AS_CONTROL_TOWER_PG_WRITES_ENABLED") != "1":
        return "disabled", None
    if not validate_test_url(url):
        return "invalid_url", None
    try:
        schema_status, _ = validate_staging_structure(url, schema=SCHEMA)
        if schema_status != "ok":
            return "schema_mismatch", None
        import psycopg
        with psycopg.connect(
            str(url).strip(), connect_timeout=8, sslmode=sslmode_for(url),
            autocommit=True,
        ) as conn:
            with conn.transaction():
                with conn.cursor() as cur:
                    cur.execute("SET LOCAL statement_timeout = '20s'")
                    cur.execute("SET LOCAL lock_timeout = '3s'")
                    cur.execute('SET LOCAL search_path TO "ct_app", pg_catalog')
                    payload = action(cur)
        return "ok", payload
    except OperationRejected as exc:
        return exc.code, None
    except Exception:
        # Unexpected exceptions can contain SQL, data or passwords.
        return "failed", None


def create_customer(url, role, name, country="Türkiye", sector=""):
    """Create one authenticated customer; serialize duplicate-name checks."""
    def action(cur):
        customer = _text(name, label="invalid_customer")
        if len(str(country or "")) > 100 or len(str(sector or "")) > 180:
            raise OperationRejected("invalid_text")
        # Serialize competing inserts for the same normalized customer name.
        cur.execute(
            "SELECT pg_advisory_xact_lock(4301, hashtext(lower(%s)))",
            (customer,),
        )
        cur.execute(
            'SELECT id FROM "ct_app"."customers" WHERE lower(name)=lower(%s) '
            "LIMIT 1", (customer,),
        )
        if cur.fetchone() is not None:
            raise OperationRejected("duplicate_customer")
        cur.execute(
            'INSERT INTO "ct_app"."customers" (name,country,sector) '
            "VALUES (%s,%s,%s) RETURNING id",
            (customer, str(country or "").strip(), str(sector or "").strip()),
        )
        return int(cur.fetchone()[0])
    return _execute(url, role, "create_customer", action)


def create_product(url, role, name, supplier, category=""):
    """Insert a verified product; name is unique in the PostgreSQL schema."""
    def action(cur):
        product = _text(name, label="invalid_product")
        vendor = _text(supplier, label="invalid_supplier")
        if len(str(category or "")) > 150:
            raise OperationRejected("invalid_text")
        cur.execute(
            'SELECT id FROM "ct_app"."product_catalog" WHERE name=%s LIMIT 1',
            (product,),
        )
        if cur.fetchone() is not None:
            raise OperationRejected("duplicate_product")
        cur.execute(
            'INSERT INTO "ct_app"."product_catalog" (name,supplier,category) '
            "VALUES (%s,%s,%s) RETURNING id",
            (product, vendor, str(category or "").strip()),
        )
        return int(cur.fetchone()[0])
    return _execute(url, role, "create_product", action)


def create_purchase_order(url, role, po_number, supplier, product_id,
                          warehouse_id, quantity_kg, unit_price, currency):
    """Validate product and warehouse in one transaction before creating PO."""
    def action(cur):
        number = _text(po_number, label="invalid_po")
        vendor = _text(supplier, label="invalid_supplier")
        product = _id(product_id)
        warehouse = _id(warehouse_id)
        quantity = _positive(quantity_kg)
        price = _positive(unit_price)
        money = _currency(currency)
        cur.execute(
            'SELECT name FROM "ct_app"."product_catalog" WHERE id=%s '
            'AND active=1', (product,),
        )
        item = cur.fetchone()
        if item is None:
            raise OperationRejected("unknown_product")
        cur.execute(
            'SELECT id FROM "ct_app"."warehouses" WHERE id=%s AND active=1',
            (warehouse,),
        )
        if cur.fetchone() is None:
            raise OperationRejected("unknown_warehouse")
        cur.execute(
            'SELECT id FROM "ct_app"."purchase_orders" WHERE po_number=%s',
            (number,),
        )
        if cur.fetchone() is not None:
            raise OperationRejected("duplicate_po")
        cur.execute(
            'INSERT INTO "ct_app"."purchase_orders" '
            '(po_number,supplier,product_id,product_name,quantity_kg,unit_price,'
            'currency,destination_warehouse_id) '
            'VALUES (%s,%s,%s,%s,%s,%s,%s,%s) RETURNING id',
            (number, vendor, product, item[0], quantity, price, money, warehouse),
        )
        return int(cur.fetchone()[0])
    return _execute(url, role, "create_purchase_order", action)


def create_shipment(url, role, purchase_order_id, shipment_ref, quantity_kg):
    """Serialize reservation of ordered quantity across concurrent shipments."""
    def action(cur):
        po = _id(purchase_order_id)
        number = _text(shipment_ref, label="invalid_shipment")
        quantity = _positive(quantity_kg)
        cur.execute(
            'SELECT quantity_kg,status,destination_warehouse_id '
            'FROM "ct_app"."purchase_orders" WHERE id=%s FOR UPDATE', (po,),
        )
        order = cur.fetchone()
        if order is None or order[1] == "İptal":
            raise OperationRejected("invalid_po")
        if order[2] is None:
            raise OperationRejected("warehouse_required")
        cur.execute(
            'SELECT COALESCE(SUM(quantity_kg),0) FROM "ct_app"."shipments" '
            "WHERE purchase_order_id=%s AND status!='İptal'", (po,),
        )
        reserved = Decimal(str(cur.fetchone()[0]))
        if reserved + quantity > Decimal(str(order[0])) + Decimal("0.001"):
            raise OperationRejected("over_shipment")
        cur.execute(
            'SELECT 1 FROM "ct_app"."shipments" '
            "WHERE purchase_order_id=%s AND shipment_ref=%s",
            (po, number),
        )
        if cur.fetchone() is not None:
            raise OperationRejected("duplicate_shipment")
        cur.execute(
            'INSERT INTO "ct_app"."shipments" '
            '(purchase_order_id,shipment_ref,quantity_kg,destination_warehouse_id) '
            'VALUES (%s,%s,%s,%s) RETURNING id',
            (po, number, quantity, order[2]),
        )
        return int(cur.fetchone()[0])
    return _execute(url, role, "create_shipment", action)


def receive_shipment(url, role, shipment_id):
    """Atomically post a shipment once, update inventory and PO status.

    Lock PO before the shipment so concurrent receipts cannot overshoot ordered
    quantity. The second receipt is always rejected; no double inventory lot.
    """
    def action(cur):
        shipment = _id(shipment_id)
        cur.execute(
            'SELECT purchase_order_id FROM "ct_app"."shipments" WHERE id=%s',
            (shipment,),
        )
        found = cur.fetchone()
        if found is None:
            raise OperationRejected("unknown_shipment")
        po_id = int(found[0])
        cur.execute(
            'SELECT product_id,product_name,quantity_kg,unit_price,currency,'
            'destination_warehouse_id,status '
            'FROM "ct_app"."purchase_orders" WHERE id=%s FOR UPDATE',
            (po_id,),
        )
        po = cur.fetchone()
        if po is None or po[6] == "İptal":
            raise OperationRejected("invalid_po")
        cur.execute(
            'SELECT purchase_order_id,quantity_kg,received_to_stock,status,'
            'destination_warehouse_id,lot_number,expiry_date '
            'FROM "ct_app"."shipments" WHERE id=%s FOR UPDATE',
            (shipment,),
        )
        row = cur.fetchone()
        if row is None or row[0] != po_id:
            raise OperationRejected("shipment_changed")
        if row[2] or row[3] == "İptal":
            raise OperationRejected("already_received_or_cancelled")
        amount = _positive(row[1])
        warehouse = row[4] or po[5]
        if warehouse is None:
            raise OperationRejected("warehouse_required")
        cur.execute(
            'SELECT COALESCE(SUM(quantity_kg),0) FROM "ct_app"."shipments" '
            'WHERE purchase_order_id=%s AND received_to_stock=1 '
            "AND status!='İptal'", (po_id,),
        )
        received = Decimal(str(cur.fetchone()[0]))
        ordered = Decimal(str(po[2]))
        if received + amount > ordered + Decimal("0.001"):
            raise OperationRejected("over_receipt")
        cur.execute(
            'INSERT INTO "ct_app"."inventory_lots" '
            '(product_id,product_name,warehouse_id,lot_number,expiry_date,'
            'quantity_received_kg,quantity_available_kg,quantity_reserved_kg,'
            'unit_cost,currency,purchase_order_id,shipment_id,received_date,notes) '
            'VALUES (%s,%s,%s,%s,%s,%s,%s,0,%s,%s,%s,%s,%s,%s) RETURNING id',
            (po[0],po[1],warehouse,row[5] or "",row[6] or "",amount,amount,
             po[3],po[4],po_id,shipment,date.today().isoformat(),
             "PostgreSQL sevkiyat girişi"),
        )
        lot_id = int(cur.fetchone()[0])
        cur.execute(
            'UPDATE "ct_app"."shipments" SET received_to_stock=1, '
            "status='Teslim Edildi',delivery_date=%s WHERE id=%s",
            (date.today().isoformat(), shipment),
        )
        status = ("Tamamlandı" if received + amount + Decimal("0.001") >= ordered
                  else "Kısmi Sevk")
        cur.execute(
            'UPDATE "ct_app"."purchase_orders" SET status=%s WHERE id=%s',
            (status, po_id),
        )
        return lot_id
    return _execute(url, role, "receive_shipment", action)


def hold_inventory_lot(url, role, lot_id, case_no, hold_kg, reason):
    """Create a quality claim and prevent held stock from appearing sellable."""
    def action(cur):
        lot = _id(lot_id)
        number = _text(case_no, label="invalid_case")
        description = _text(reason, label="invalid_case", max_length=1500)
        held = _positive(hold_kg)
        cur.execute(
            'SELECT product_id,product_name,quantity_available_kg,'
            'quantity_reserved_kg,quality_status,quality_hold_kg,'
            'purchase_order_id,shipment_id '
            'FROM "ct_app"."inventory_lots" WHERE id=%s FOR UPDATE',
            (lot,),
        )
        row = cur.fetchone()
        if row is None:
            raise OperationRejected("unknown_lot")
        if row[4] not in (None,"Released",""):
            raise OperationRejected("lot_already_held")
        available = Decimal(str(row[2] or 0)) - Decimal(str(row[3] or 0))
        previous_hold = Decimal(str(row[5] or 0))
        if previous_hold > 0 or held > available:
            raise OperationRejected("hold_exceeds_available")
        cur.execute(
            'INSERT INTO "ct_app"."quality_cases" '
            '(case_no,opened_date,product_id,product_name,inventory_lot_id,'
            'purchase_order_id,shipment_id,affected_quantity_kg,description) '
            'VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING id',
            (number,date.today().isoformat(),row[0],row[1],lot,
             row[6],row[7],held,description),
        )
        case_id = int(cur.fetchone()[0])
        cur.execute(
            'UPDATE "ct_app"."inventory_lots" SET quality_status=%s,'
            'quality_hold_kg=%s,quality_case_id=%s WHERE id=%s',
            ("HOLD",held,case_id,lot),
        )
        return case_id
    return _execute(url, role, "hold_inventory_lot", action)


def create_payable(url, role, supplier, purchase_order_id, invoice_no,
                   due_date, amount, currency):
    """Create an AP invoice with advisory-locked duplicate detection."""
    def action(cur):
        po = _id(purchase_order_id)
        vendor = _text(supplier, label="invalid_supplier")
        invoice = _text(invoice_no, label="invalid_invoice")
        due = _date(due_date)
        balance = _positive(amount)
        money = _currency(currency)
        cur.execute(
            'SELECT supplier FROM "ct_app"."purchase_orders" WHERE id=%s',
            (po,),
        )
        order = cur.fetchone()
        if order is None or order[0] != vendor:
            raise OperationRejected("invalid_po")
        cur.execute(
            "SELECT pg_advisory_xact_lock(4302,hashtext(%s))",
            (str(po) + "|" + invoice,),
        )
        cur.execute(
            'SELECT id FROM "ct_app"."payables" WHERE '
            "purchase_order_id=%s AND invoice_no=%s LIMIT 1",
            (po, invoice),
        )
        if cur.fetchone() is not None:
            raise OperationRejected("duplicate_invoice")
        cur.execute(
            'INSERT INTO "ct_app"."payables" '
            '(supplier,purchase_order_id,invoice_no,due_date,amount,currency) '
            'VALUES (%s,%s,%s,%s,%s,%s) RETURNING id',
            (vendor,po,invoice,due,balance,money),
        )
        return int(cur.fetchone()[0])
    return _execute(url, role, "create_payable", action)


def pay_supplier(url, role, payable_id, account_id, amount, reference,
                 payment_date):
    """Atomic AP settlement; lock invoice and bank, guard HOLD and reference."""
    def action(cur):
        payable = _id(payable_id)
        bank = _id(account_id)
        paid_now = _positive(amount)
        reference_id = _text(reference, label="reference_required")
        when = _date(payment_date)
        cur.execute(
            'SELECT purchase_order_id,amount,paid_amount,currency,status '
            'FROM "ct_app"."payables" WHERE id=%s FOR UPDATE',
            (payable,),
        )
        invoice = cur.fetchone()
        if invoice is None or invoice[4] == "İptal":
            raise OperationRejected("unknown_payable")
        remaining = Decimal(str(invoice[1] or 0))-Decimal(str(invoice[2] or 0))
        if paid_now > remaining or remaining <= 0:
            raise OperationRejected("overpayment")
        if invoice[0] is not None:
            cur.execute(
                'SELECT EXISTS (SELECT 1 FROM "ct_app"."inventory_lots" '
                'WHERE purchase_order_id=%s AND quality_hold_kg>0)',
                (invoice[0],),
            )
            if cur.fetchone()[0]:
                raise OperationRejected("quality_hold_blocks_payment")
        cur.execute(
            'SELECT currency,balance,active FROM "ct_app"."cash_accounts" '
            'WHERE id=%s FOR UPDATE',
            (bank,),
        )
        account = cur.fetchone()
        if account is None or not account[2]:
            raise OperationRejected("unknown_account")
        if account[0] != invoice[3]:
            raise OperationRejected("currency_mismatch")
        if Decimal(str(account[1] or 0)) < paid_now:
            raise OperationRejected("insufficient_funds")
        cur.execute(
            'SELECT 1 FROM "ct_app"."finance_transactions" '
            "WHERE payable_id=%s AND transaction_type='Ödeme' "
            "AND reference=%s LIMIT 1",
            (payable,reference_id),
        )
        if cur.fetchone() is not None:
            raise OperationRejected("duplicate_payment")
        status = ("Kapandı" if paid_now == remaining else "Kısmi")
        cur.execute(
            'UPDATE "ct_app"."payables" SET paid_amount=paid_amount+%s,'
            'status=%s WHERE id=%s', (paid_now,status,payable),
        )
        cur.execute(
            'INSERT INTO "ct_app"."finance_transactions" '
            '(transaction_type,payable_id,transaction_date,amount,currency,'
            'account_id,reference) VALUES (%s,%s,%s,%s,%s,%s,%s) RETURNING id',
            ("Ödeme",payable,when,paid_now,invoice[3],bank,reference_id),
        )
        payment_id = int(cur.fetchone()[0])
        cur.execute(
            'UPDATE "ct_app"."cash_accounts" SET balance=balance-%s '
            'WHERE id=%s', (paid_now,bank),
        )
        return payment_id
    return _execute(url, role, "pay_supplier", action)
