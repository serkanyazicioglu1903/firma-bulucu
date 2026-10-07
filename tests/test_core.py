from pathlib import Path

import control_tower
from security_admin import hash_password, verify_password


def use_temp_db(tmp_path):
    db = Path(tmp_path) / "test_control_tower.db"
    control_tower.DB_PATH = db
    control_tower.init_db()
    control_tower.seed_once()
    control_tower.seed_product_catalog()
    control_tower.seed_warehouses()
    return db


def test_database_schema_and_seed(tmp_path):
    use_temp_db(tmp_path)
    customers = control_tower.query_df("SELECT COUNT(*) AS n FROM customers")
    products = control_tower.query_df("SELECT COUNT(*) AS n FROM product_catalog")
    warehouses = control_tower.query_df("SELECT COUNT(*) AS n FROM warehouses")
    assert int(customers.iloc[0]["n"]) >= 2
    assert int(products.iloc[0]["n"]) >= 1
    assert int(warehouses.iloc[0]["n"]) >= 2


def test_quote_calculator_positive_case():
    calc = control_tower.calculate_quote(
        quantity_kg=24000,
        buy_price_per_kg=2.0,
        buy_fx_to_base=1.0,
        freight_total_base=1200,
        customs_rate_pct=0,
        customs_fixed_base=0,
        import_other_total_base=300,
        handling_total_base=500,
        finance_rate_pct=45,
        prepayment_days=35,
        stock_days=30,
        customer_credit_days=90,
        sell_price_per_kg=2.8,
        sell_fx_to_base=1.0,
        sales_commission_pct=0,
        target_margin_pct=10,
    )
    assert calc["total_cost_per_kg"] > 2.0
    assert calc["finance_days"] == 155
    assert calc["required_sell_price"] > calc["total_cost_per_kg"]


def test_password_hash_roundtrip():
    value = hash_password("Strong-Test-Password-1903")
    assert verify_password("Strong-Test-Password-1903", value)
    assert not verify_password("wrong-password", value)


def test_stock_snapshot_runs(tmp_path):
    use_temp_db(tmp_path)
    df = control_tower.stock_snapshot()
    assert "name" in df.columns
    assert "status" in df.columns
