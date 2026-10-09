"""Rollback-only PostgreSQL business workflow pilot for AS Control Tower.

Exercises quote economics, partial receipt, quality HOLD, AR settlement, AP
balances and account movement against *fictional* ct_staging records.
This does NOT switch live modules away from SQLite or persist demo data.
"""
from datetime import date, timedelta
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
import secrets

from scripts.staging_validate import validate_staging_structure
from scripts.staging_transaction_smoke import validate_test_url

SCHEMA = "ct_staging"
TEST_TABLES = (
    "customers", "product_catalog", "opportunities", "quotes", "tasks",
    "warehouses", "purchase_orders", "shipments", "inventory_lots",
    "quality_cases", "receivables", "payables", "cash_accounts",
    "finance_transactions",
)


class BusinessRuleError(ValueError):
    """An intentionally safe, data-free business validation failure."""


class _RollbackDemo(Exception):
    """Only for ensuring the example is never committed."""


def decimal_value(value, *, positive=False):
    try:
        number = Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        raise BusinessRuleError("Invalid amount.") from None
    if not number.is_finite() or (number <= 0 if positive else number < 0):
        raise BusinessRuleError("Amount is not permitted.")
    return number


def quote_preview(quantity_kg, buy_price, buy_fx, freight_eur, sell_price,
                  finance_rate_pct, finance_days, commission_pct=0):
    """Deterministic EUR per-kg estimates, never sums across currencies.

    Buy price is in the purchase currency, FX converts it into EUR. Freight is
    already EUR per shipment. Sell price is EUR/kg. Day-count is ACT/365.
    """
    qty = decimal_value(quantity_kg, positive=True)
    purchase = decimal_value(buy_price)
    fx = decimal_value(buy_fx, positive=True)
    freight = decimal_value(freight_eur)
    sell = decimal_value(sell_price, positive=True)
    rate = decimal_value(finance_rate_pct)
    commission_pct = decimal_value(commission_pct)
    if rate > 100 or commission_pct > 100:
        raise BusinessRuleError("Rates must be within 0 to 100 percent.")
    if not isinstance(finance_days, int) or not 0 <= finance_days <= 3650:
        raise BusinessRuleError("Invalid financing days.")
    landed = purchase * fx + freight / qty
    financing = landed * rate / 100 * Decimal(finance_days) / 365
    commission = sell * commission_pct / 100
    cost = landed + financing + commission
    profit = sell - cost
    return {
        "cost_eur_kg": float(cost),
        "profit_eur_kg": float(profit),
        "profit_eur_total": float(profit * qty),
        "margin_pct": float(profit / sell * 100),
        "landed_eur_kg": float(landed),
    }


def stock_after_receipt(ordered_kg, already_received_kg, incoming_kg, hold_kg):
    ordered = decimal_value(ordered_kg, positive=True)
    already = decimal_value(already_received_kg)
    incoming = decimal_value(incoming_kg, positive=True)
    hold = decimal_value(hold_kg)
    if already + incoming > ordered or hold > incoming:
        raise BusinessRuleError("Over-receipt or invalid quality hold.")
    return {
        "received": float(already + incoming),
        "available": float(incoming - hold),
        "hold": float(hold),
        "remaining": float(ordered - already - incoming),
    }


def settle_invoice(invoice_total, previously_paid, payment, fx_to_eur):
    amount = decimal_value(invoice_total, positive=True)
    paid = decimal_value(previously_paid)
    new_payment = decimal_value(payment, positive=True)
    fx = decimal_value(fx_to_eur, positive=True)
    if paid + new_payment > amount:
        raise BusinessRuleError("Payment exceeds invoice outstanding amount.")
    balance = amount - paid - new_payment
    return {
        "paid": float(paid + new_payment),
        "outstanding": float(balance),
        "outstanding_eur": float(balance * fx),
        "status": "Kapandı" if balance == 0 else "Kısmi",
    }


def _execute(cur, sql, params=()):
    """Always use parameters for data; every table name is a fixed literal."""
    cur.execute(sql, params)


def run_staging_business_pilot(url):
    """Returns (status, safe_summary) after forced rollback, without row data."""
    if not validate_test_url(url):
        return "invalid_url", {}
    status, _issues = validate_staging_structure(url)
    if status != "ok":
        return "schema_mismatch", {}

    quote = quote_preview(1000, 2.20, 0.92, 450, 3.10, 10, 90, 1)
    stock = stock_after_receipt(1000, 0, 600, 100)
    ar = settle_invoice(3100, 0, 1300, 1)
    ap = settle_invoice(2200, 0, 800, 0.92)
    test_id = -(secrets.randbelow(1 << 54) + 100)
    marker = "CT_PILOT_" + secrets.token_hex(12)
    now = date.today()
    due = (now + timedelta(days=90)).isoformat()
    try:
        import psycopg
        with psycopg.connect(
            str(url).strip(), connect_timeout=8, sslmode="require", autocommit=True
        ) as conn:
            try:
                with conn.transaction():
                    with conn.cursor() as cur:
                        _execute(cur, "SET LOCAL statement_timeout = '25000ms'")
                        _execute(cur, "SET LOCAL lock_timeout = '3000ms'")
                        _execute(cur, 'SET LOCAL search_path TO "ct_staging", pg_catalog')
                        # CRM and quote pricing: EUR amount explicitly converted.
                        _execute(cur, 'INSERT INTO "ct_staging"."customers" (id,name) VALUES (%s,%s)',
                                 (test_id, marker+"_CUSTOMER"))
                        _execute(cur, 'INSERT INTO "ct_staging"."product_catalog" (id,name) VALUES (%s,%s)',
                                 (test_id, marker+"_PRODUCT"))
                        _execute(cur, 'INSERT INTO "ct_staging"."opportunities" (id,customer_id,product) '
                                      'VALUES (%s,%s,%s)',
                                 (test_id,test_id,marker+"_PRODUCT"))
                        _execute(cur, 'INSERT INTO "ct_staging"."quotes" '
                                      '(id,customer_id,opportunity_id,product_name,quantity_kg,'
                                      'buy_price_per_kg,buy_currency,buy_fx_to_base,'
                                      'freight_total_base,finance_rate_pct,finance_days,'
                                      'sell_price_per_kg,sell_currency,'
                                      'total_cost_per_kg,profit_per_kg,profit_total_base,margin_pct) '
                                      'VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)',
                                 (test_id,test_id,test_id,marker+"_PRODUCT",1000,2.2,"USD",.92,
                                  450,10,90,3.1,"EUR",quote["cost_eur_kg"],
                                  quote["profit_eur_kg"],quote["profit_eur_total"],quote["margin_pct"]))
                        _execute(cur, 'SELECT q.profit_total_base,c.name '
                                      'FROM "ct_staging"."quotes" q '
                                      'JOIN "ct_staging"."customers" c ON c.id=q.customer_id '
                                      'WHERE q.id=%s', (test_id,))
                        row = cur.fetchone()
                        if not row or row[1] != marker+"_CUSTOMER" or abs(row[0] - quote["profit_eur_total"]) > 0.0001:
                            raise BusinessRuleError("Quotation reconciliation failed.")
                        _execute(cur, 'INSERT INTO "ct_staging"."tasks" (id,title) VALUES (%s,%s)',
                                 (test_id, marker+"_FOLLOWUP"))
                        # Purchase order, partial receipt, quality hold.
                        _execute(cur, 'INSERT INTO "ct_staging"."warehouses" (id,name) VALUES (%s,%s)',
                                 (test_id,marker+"_WAREHOUSE"))
                        _execute(cur, 'INSERT INTO "ct_staging"."purchase_orders" '
                                      '(id,po_number,supplier,product_id,product_name,quantity_kg,'
                                      'unit_price,currency,destination_warehouse_id) '
                                      'VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)',
                                 (test_id,marker+"_PO",marker+"_SUPPLIER",test_id,marker+"_PRODUCT",
                                  1000,2.2,"USD",test_id))
                        _execute(cur, 'INSERT INTO "ct_staging"."shipments" '
                                      '(id,purchase_order_id,quantity_kg,destination_warehouse_id) '
                                      'VALUES (%s,%s,%s,%s)',(test_id,test_id,600,test_id))
                        _execute(cur, 'UPDATE "ct_staging"."shipments" SET received_to_stock=1 '
                                      'WHERE id=%s AND received_to_stock=0',(test_id,))
                        if cur.rowcount != 1:
                            raise BusinessRuleError("Duplicate shipment receipt.")
                        _execute(cur, 'INSERT INTO "ct_staging"."inventory_lots" '
                                      '(id,product_id,product_name,warehouse_id,purchase_order_id,'
                                      'shipment_id,quantity_received_kg,quantity_available_kg,quality_hold_kg,quality_status) '
                                      'VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)',
                                 (test_id,test_id,marker+"_PRODUCT",test_id,test_id,test_id,
                                  stock["received"],600,stock["hold"],"HOLD"))
                        _execute(cur, 'INSERT INTO "ct_staging"."quality_cases" '
                                      '(id,case_no,opened_date,product_id,product_name,'
                                      'inventory_lot_id,purchase_order_id,shipment_id,description) '
                                      'VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)',
                                 (test_id,marker+"_QUALITY",now.isoformat(),test_id,
                                  marker+"_PRODUCT",test_id,test_id,test_id,
                                  "Isolated fictional PostgreSQL business pilot"))
                        _execute(cur, 'SELECT l.quantity_received_kg,l.quantity_available_kg,'
                                      'l.quality_hold_kg, s.received_to_stock '
                                      'FROM "ct_staging"."inventory_lots" l '
                                      'JOIN "ct_staging"."shipments" s ON l.shipment_id=s.id '
                                      'WHERE l.id=%s', (test_id,))
                        record = cur.fetchone()
                        if not record or record[3] != 1 or abs(record[0]-600)>0.0001 or abs(record[1]-record[2]-stock["available"])>0.0001:
                            raise BusinessRuleError("Inventory HOLD reconciliation failed.")
                        # Finance: no cross-currency sum without FX conversion.
                        _execute(cur, 'INSERT INTO "ct_staging"."cash_accounts" (id,name,currency,balance) '
                                      'VALUES (%s,%s,%s,%s)',(test_id,marker+"_BANK","EUR",0))
                        _execute(cur, 'INSERT INTO "ct_staging"."receivables" '
                                      '(id,customer_id,due_date,amount,paid_amount,currency,fx_to_base) '
                                      'VALUES (%s,%s,%s,%s,%s,%s,%s)',
                                 (test_id,test_id,due,3100,0,"EUR",1))
                        _execute(cur, 'INSERT INTO "ct_staging"."payables" '
                                      '(id,supplier,purchase_order_id,due_date,amount,paid_amount,currency,fx_to_base) '
                                      'VALUES (%s,%s,%s,%s,%s,%s,%s,%s)',
                                 (test_id,marker+"_SUPPLIER",test_id,due,2200,0,"USD",.92))
                        _execute(cur, 'UPDATE "ct_staging"."receivables" SET paid_amount=%s,status=%s '
                                      'WHERE id=%s AND paid_amount=0',
                                 (ar["paid"],ar["status"],test_id))
                        if cur.rowcount != 1:
                            raise BusinessRuleError("Receivable optimistic update failed.")
                        _execute(cur, 'UPDATE "ct_staging"."payables" SET paid_amount=%s,status=%s '
                                      'WHERE id=%s AND paid_amount=0',
                                 (ap["paid"],ap["status"],test_id))
                        if cur.rowcount != 1:
                            raise BusinessRuleError("Payable optimistic update failed.")
                        _execute(cur, 'INSERT INTO "ct_staging"."finance_transactions" '
                                      '(id,transaction_type,receivable_id,transaction_date,'
                                      'amount,currency,fx_to_base,account_id) '
                                      'VALUES (%s,%s,%s,%s,%s,%s,%s,%s)',
                                 (test_id,"Tahsilat",test_id,now.isoformat(),1300,"EUR",1,test_id))
                        _execute(cur, 'UPDATE "ct_staging"."cash_accounts" SET balance=balance+%s '
                                      'WHERE id=%s',(1300,test_id))
                        _execute(cur, 'SELECT r.amount-r.paid_amount,p.amount-p.paid_amount,'
                                      'p.fx_to_base,a.balance '
                                      'FROM "ct_staging"."receivables" r '
                                      'JOIN "ct_staging"."payables" p ON p.id=%s '
                                      'JOIN "ct_staging"."cash_accounts" a ON a.id=%s '
                                      'WHERE r.id=%s',(test_id,test_id,test_id))
                        fin = cur.fetchone()
                        if (not fin or abs(fin[0]-ar["outstanding"]) > .0001
                                or abs(fin[1]*fin[2]-ap["outstanding_eur"]) > .0001
                                or abs(fin[3]-1300) > .0001):
                            raise BusinessRuleError("Finance reconciliation failed.")
                    raise _RollbackDemo()
            except _RollbackDemo:
                pass
            # Verify the whole sample was removed by rollback.
            with conn.cursor() as cur:
                _execute(cur, "SET statement_timeout = '10000ms'")
                for table in TEST_TABLES:
                    # Identifiers are trusted, constant, not user input.
                    _execute(cur, 'SELECT 1 FROM "ct_staging"."' + table + '" '
                                  'WHERE id=%s LIMIT 1', (test_id,))
                    if cur.fetchone() is not None:
                        return "failed", {}
        return "passed", {
            "steps": ["CRM", "Teklif ve gerçek maliyet", "Satın alma", "Kısmi mal kabul",
                      "Kalite HOLD", "Tahsilat", "Borç ve kur", "Banka hareketi"],
            "quantity_kg": 1000, "received_kg": 600, "hold_kg": 100,
            "available_kg": stock["available"], "remaining_kg": stock["remaining"],
            "profit_eur_total": round(quote["profit_eur_total"], 2),
            "receivable_eur": ar["outstanding"],
            "payable_eur": round(ap["outstanding_eur"], 2),
        }
    except Exception:
        # Never leak database errors, credentials or fictional SQL row content.
        return "failed", {}
