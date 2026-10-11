"""AS Control Tower manual quote economics — no demo seed, database or network.

All amounts are user-supplied. Rates are MANUAL, never live market rates.
VAT is excluded; customs and other import charges are explicit base-currency
totals to avoid pretending a particular tax/duty assessment is universal.

This is a preliminary commercial estimate, not an accounting entry, invoice,
supplier commitment, tenant authorization or saved company record.
"""
from decimal import Decimal, InvalidOperation
from scripts.group_company_catalog import COMPANY_LABELS

CURRENCIES = frozenset({"EUR", "USD", "GBP", "TRY"})
DAY_LIMIT = 3650
MAX_QUANTITY_KG = Decimal("1000000000")
MAX_PRICE = Decimal("1000000000")


class QuoteInputError(ValueError):
    """No user-supplied prices or customer names are embedded in errors."""

    def __init__(self, code="invalid_input"):
        self.code = code
        super().__init__(code)


def _amount(value, name, *, positive=False, maximum=MAX_PRICE):
    if type(value) is bool or value is None:
        raise QuoteInputError(name)
    try:
        d = Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        raise QuoteInputError(name) from None
    if not d.is_finite() or d > maximum or (d <= 0 if positive else d < 0):
        raise QuoteInputError(name)
    return d


def _rate(value, name, *, strict_100=False):
    d = _amount(value, name)
    if d > 100 or (strict_100 and d >= 100):
        raise QuoteInputError(name)
    return d


def _days(value, name):
    if type(value) is not int or value < 0 or value > DAY_LIMIT:
        raise QuoteInputError(name)
    return Decimal(value)


def _currency(value):
    if not isinstance(value, str) or value not in CURRENCIES:
        raise QuoteInputError("currency")
    return value


def _fx(rate, from_currency, to_currency):
    if from_currency == to_currency:
        # A caller can never accidentally convert identical currencies
        # at a non-unit exchange rate.
        if Decimal(str(rate)) != 1:
            raise QuoteInputError("same_currency_fx")
        return Decimal(1)
    return _amount(rate, "fx_required", positive=True)


def calculate_real_quote(*, company_code, quantity_kg, buy_price_per_kg,
                         buy_currency, buy_fx_to_base, base_currency,
                         sell_price_per_kg, sell_currency, sell_fx_to_base,
                         freight_total_base=0, customs_total_base=0,
                         import_other_total_base=0, handling_total_base=0,
                         annual_finance_rate_pct=0, prepayment_pct=0,
                         prepayment_lead_days=0, supplier_balance_due_days=0,
                         stock_days=0, customer_credit_days=0,
                         sales_commission_pct=0, target_margin_pct=0):
    """Calculate landed unit cost, working capital and margin in base currency.

    Supplier timing convention:
      - prepayment happens N days BEFORE goods arrive
      - remaining goods payment happens N days AFTER goods arrive
      - all freight/duties/handling outlays are assumed due at arrival
      - collection happens stock_days + customer_credit_days AFTER arrival
    Simple annual ACT/365 finance; no compounding or negative financing.
    An entered sale price of 0 means target price preview ONLY.
    """
    if not isinstance(company_code, str) or company_code not in COMPANY_LABELS:
        raise QuoteInputError("company_required")
    base = _currency(base_currency)
    buy = _currency(buy_currency)
    sell = _currency(sell_currency)
    quantity = _amount(quantity_kg, "quantity_required", positive=True,
                       maximum=MAX_QUANTITY_KG)
    buy_price = _amount(buy_price_per_kg, "buy_price_required", positive=True)
    sell_price = _amount(sell_price_per_kg, "sell_price")
    buy_fx = _fx(buy_fx_to_base, buy, base)
    sell_fx = _fx(sell_fx_to_base, sell, base)
    freight = _amount(freight_total_base, "freight")
    customs = _amount(customs_total_base, "customs")
    import_other = _amount(import_other_total_base, "import_other")
    handling = _amount(handling_total_base, "handling")
    annual_rate = _rate(annual_finance_rate_pct, "finance_rate")
    prepct = _rate(prepayment_pct, "prepayment_pct")
    commission = _rate(sales_commission_pct, "commission", strict_100=True)
    margin_target = _rate(target_margin_pct, "margin_target", strict_100=True)
    advance_days = _days(prepayment_lead_days, "prepayment_lead_days")
    balance_days = _days(supplier_balance_due_days, "supplier_balance_due_days")
    hold_days = _days(stock_days, "stock_days")
    customer_days = _days(customer_credit_days, "customer_credit_days")

    goods = quantity * buy_price * buy_fx
    logistics = freight + customs + import_other + handling
    landed_total = goods + logistics
    collection_after_arrival = hold_days + customer_days
    prep = prepct / Decimal(100)
    # Goods-funded days are weighted by invoice payment schedule; supplier
    # payment that is due after customer collection has zero finance days.
    weighted_goods_days = (
        prep * (advance_days + collection_after_arrival)
        + (Decimal(1) - prep) * max(
            Decimal(0), collection_after_arrival - balance_days
        )
    )
    annual_factor = annual_rate / Decimal(100) / Decimal(365)
    goods_finance = goods * annual_factor * weighted_goods_days
    logistics_finance = logistics * annual_factor * collection_after_arrival
    finance_total = goods_finance + logistics_finance
    total_cost = landed_total + finance_total
    cost_per_kg = total_cost / quantity

    effective_sales_fraction = (Decimal(1) - commission / Decimal(100))
    target_cost_fraction = (Decimal(1) - margin_target / Decimal(100))
    break_even_sell_price = (
        cost_per_kg / effective_sales_fraction / sell_fx
    )
    required_sell_price = (
        cost_per_kg / target_cost_fraction / effective_sales_fraction / sell_fx
    )

    result = {
        "company_code": company_code,
        "base_currency": base,
        "buy_currency": buy,
        "sell_currency": sell,
        "quantity_kg": quantity,
        "goods_base": goods,
        "logistics_base": logistics,
        "landed_total_base": landed_total,
        "landed_per_kg_base": landed_total / quantity,
        "goods_finance_base": goods_finance,
        "logistics_finance_base": logistics_finance,
        "finance_total_base": finance_total,
        "finance_per_kg_base": finance_total / quantity,
        "weighted_goods_finance_days": weighted_goods_days,
        "collection_after_arrival_days": collection_after_arrival,
        "total_cost_base": total_cost,
        "cost_per_kg_base": cost_per_kg,
        "break_even_sell_price": break_even_sell_price,
        "target_margin_pct": margin_target,
        "required_sell_price": required_sell_price,
        "gross_sales_base": None,
        "commission_base": None,
        "net_sales_base": None,
        "profit_base": None,
        "profit_per_kg_base": None,
        "margin_pct": None,
        "meets_target": None,
    }
    if sell_price > 0:
        gross = quantity * sell_price * sell_fx
        commission_total = gross * commission / Decimal(100)
        net_sales = gross - commission_total
        profit = net_sales - total_cost
        actual_margin = profit / net_sales * Decimal(100)
        result.update({
            "gross_sales_base": gross,
            "commission_base": commission_total,
            "net_sales_base": net_sales,
            "profit_base": profit,
            "profit_per_kg_base": profit / quantity,
            "margin_pct": actual_margin,
            "meets_target": actual_margin >= margin_target,
        })
    return result
