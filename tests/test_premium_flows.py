import sys
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import control_tower
from ai_manager import answer_question, build_ceo_brief_text


def setup_db(tmp_path):
    db = tmp_path / "premium_test.db"
    control_tower.DB_PATH = db
    control_tower.init_db()
    control_tower.seed_once()
    control_tower.seed_product_catalog()
    control_tower.seed_warehouses()
    return db


def id_for(table, name):
    return int(
        control_tower.query_df(
            f"SELECT id FROM {table} WHERE name=?", (name,)
        ).iloc[0]["id"]
    )


def test_product_to_customer_recommendation_is_stable(tmp_path):
    setup_db(tmp_path)
    pid = id_for("product_catalog", "Fat Powder FI FP 80 PR 01")

    recs = control_tower.recommendation_rows(product_id=pid)
    assert recs["Müşteri"].tolist() == ["Pakmaya"]
    assert int(recs.iloc[0]["customer_id"]) == id_for("customers", "Pakmaya")

    ok, _ = control_tower.create_opportunity_from_recommendation(
        int(recs.iloc[0]["customer_id"]), pid, 250000, "Serkan"
    )
    assert ok

    recs_after = control_tower.recommendation_rows(product_id=pid)
    assert recs_after.empty

    ok2, msg2 = control_tower.create_opportunity_from_recommendation(
        id_for("customers", "Pakmaya"), pid, 250000, "Serkan"
    )
    assert not ok2
    assert "zaten" in msg2.lower()


def test_customer_product_status_exclusion(tmp_path):
    setup_db(tmp_path)
    cid = id_for("customers", "Pakmaya")
    pid = id_for("product_catalog", "Vital Wheat Gluten")

    before = control_tower.recommendation_rows(customer_id=cid)
    assert pid in before["product_id"].tolist()

    control_tower.save_customer_product_status(
        cid, pid, "Uygun Değil", "", 0, "Teknik olarak uygun değil"
    )
    after = control_tower.recommendation_rows(customer_id=cid)
    assert pid not in after["product_id"].tolist()


def test_quote_true_cost_and_required_price(tmp_path):
    setup_db(tmp_path)
    calc = control_tower.calculate_quote(
        quantity_kg=24000,
        buy_price_per_kg=2.00,
        buy_fx_to_base=1,
        freight_total_base=1200,
        customs_rate_pct=0,
        customs_fixed_base=0,
        import_other_total_base=300,
        handling_total_base=500,
        finance_rate_pct=45,
        prepayment_days=35,
        stock_days=30,
        customer_credit_days=90,
        sell_price_per_kg=2.80,
        sell_fx_to_base=1,
        sales_commission_pct=0,
        target_margin_pct=10,
    )
    assert calc["finance_days"] == 155
    assert calc["total_cost_per_kg"] > calc["landed_cost_per_kg"]
    assert calc["required_sell_price"] > calc["total_cost_per_kg"]
    assert calc["profit_total_base"] > 0


def test_quality_hold_removed_from_usable_stock(tmp_path):
    setup_db(tmp_path)
    pid = id_for("product_catalog", "Fat Powder FI FP 80 PR 01")
    wid = id_for("warehouses", "Merkez Depo")

    control_tower.execute(
        """INSERT INTO inventory_lots
        (product_id,product_name,warehouse_id,lot_number,
         quantity_received_kg,quantity_available_kg,quantity_reserved_kg,quality_status)
        VALUES (?,?,?,?,?,?,?,?)""",
        (pid, "Fat Powder FI FP 80 PR 01", wid, "FREE-1", 1000, 1000, 100, "Released")
    )
    control_tower.execute(
        """INSERT INTO inventory_lots
        (product_id,product_name,warehouse_id,lot_number,
         quantity_received_kg,quantity_available_kg,quantity_reserved_kg,quality_status)
        VALUES (?,?,?,?,?,?,?,?)""",
        (pid, "Fat Powder FI FP 80 PR 01", wid, "HOLD-1", 500, 500, 0, "HOLD")
    )

    snap = control_tower.stock_snapshot()
    row = snap[snap["id"] == pid].iloc[0]
    assert float(row["net_available_kg"]) == 900
    assert float(row["quality_hold_kg"]) == 500


def test_partial_and_complete_shipment_receiving(tmp_path):
    setup_db(tmp_path)
    pid = id_for("product_catalog", "Vital Wheat Gluten")
    wid = id_for("warehouses", "Merkez Depo")

    control_tower.execute(
        """INSERT INTO purchase_orders
        (po_number,supplier,product_id,product_name,quantity_kg,unit_price,currency,
         destination_warehouse_id,status)
        VALUES (?,?,?,?,?,?,?,?,?)""",
        ("PO-TEST-1","Fidelinka",pid,"Vital Wheat Gluten",1000,1.6,"EUR",wid,"Sipariş Verildi")
    )
    poid = int(control_tower.query_df(
        "SELECT id FROM purchase_orders WHERE po_number='PO-TEST-1'"
    ).iloc[0]["id"])

    for ref, qty in [("S1",400),("S2",600)]:
        control_tower.execute(
            """INSERT INTO shipments
            (purchase_order_id,shipment_ref,quantity_kg,status,destination_warehouse_id,lot_number)
            VALUES (?,?,?,?,?,?)""",
            (poid,ref,qty,"Yolda",wid,ref+"-LOT")
        )

    s1 = int(control_tower.query_df(
        "SELECT id FROM shipments WHERE shipment_ref='S1'"
    ).iloc[0]["id"])
    s2 = int(control_tower.query_df(
        "SELECT id FROM shipments WHERE shipment_ref='S2'"
    ).iloc[0]["id"])

    ok1, _ = control_tower.receive_shipment_to_stock(s1)
    assert ok1
    status1 = control_tower.query_df(
        "SELECT status FROM purchase_orders WHERE id=?", (poid,)
    ).iloc[0]["status"]
    assert status1 == "Kısmi Sevk"

    ok2, _ = control_tower.receive_shipment_to_stock(s2)
    assert ok2
    status2 = control_tower.query_df(
        "SELECT status FROM purchase_orders WHERE id=?", (poid,)
    ).iloc[0]["status"]
    assert status2 == "Tamamlandı"

    total = float(control_tower.query_df(
        "SELECT SUM(quantity_available_kg) AS q FROM inventory_lots WHERE purchase_order_id=?",
        (poid,)
    ).iloc[0]["q"])
    assert total == 1000


def test_receivable_payment_is_currency_safe_and_atomic(tmp_path):
    setup_db(tmp_path)
    cid = id_for("customers", "Pakmaya")
    due = str(date.today() + timedelta(days=30))

    control_tower.execute(
        """INSERT INTO receivables
        (customer_id,invoice_no,due_date,amount,paid_amount,currency,fx_to_base,base_currency,status)
        VALUES (?,?,?,?,?,?,?,?,?)""",
        (cid,"INV-1",due,1000,0,"EUR",1,"EUR","Açık")
    )
    rid = int(control_tower.query_df(
        "SELECT id FROM receivables WHERE invoice_no='INV-1'"
    ).iloc[0]["id"])

    control_tower.execute(
        """INSERT INTO cash_accounts
        (name,currency,balance,fx_to_base,base_currency,active)
        VALUES ('EUR Bank','EUR',0,1,'EUR',1)"""
    )
    control_tower.execute(
        """INSERT INTO cash_accounts
        (name,currency,balance,fx_to_base,base_currency,active)
        VALUES ('USD Bank','USD',0,0.9,'EUR',1)"""
    )
    eur = int(control_tower.query_df(
        "SELECT id FROM cash_accounts WHERE name='EUR Bank'"
    ).iloc[0]["id"])
    usd = int(control_tower.query_df(
        "SELECT id FROM cash_accounts WHERE name='USD Bank'"
    ).iloc[0]["id"])

    bad, msg = control_tower.record_receivable_payment(
        rid, 300, date.today(), usd, "BAD", ""
    )
    assert not bad
    assert "para birimi" in msg.lower()
    row = control_tower.query_df("SELECT paid_amount,status FROM receivables WHERE id=?", (rid,)).iloc[0]
    assert float(row["paid_amount"]) == 0
    assert row["status"] == "Açık"

    ok, _ = control_tower.record_receivable_payment(
        rid, 400, date.today(), eur, "P1", ""
    )
    assert ok
    row = control_tower.query_df("SELECT paid_amount,status FROM receivables WHERE id=?", (rid,)).iloc[0]
    assert float(row["paid_amount"]) == 400
    assert row["status"] == "Kısmi"
    balance = float(control_tower.query_df(
        "SELECT balance FROM cash_accounts WHERE id=?", (eur,)
    ).iloc[0]["balance"])
    assert balance == 400

    over, _ = control_tower.record_receivable_payment(
        rid, 700, date.today(), eur, "OVER", ""
    )
    assert not over
    row2 = control_tower.query_df("SELECT paid_amount FROM receivables WHERE id=?", (rid,)).iloc[0]
    assert float(row2["paid_amount"]) == 400


def test_cash_forecast_filters_base_currency(tmp_path):
    setup_db(tmp_path)
    cid = id_for("customers", "Pakmaya")
    due = str(date.today() + timedelta(days=10))

    control_tower.execute(
        """INSERT INTO cash_accounts
        (name,currency,balance,fx_to_base,base_currency,active)
        VALUES ('EUR Main','EUR',1000,1,'EUR',1)"""
    )
    control_tower.execute(
        """INSERT INTO cash_accounts
        (name,currency,balance,fx_to_base,base_currency,active)
        VALUES ('GBP Managed','GBP',500,1,'GBP',1)"""
    )
    control_tower.execute(
        """INSERT INTO receivables
        (customer_id,invoice_no,due_date,amount,currency,fx_to_base,base_currency,status)
        VALUES (?,?,?,?,?,?,?,?)""",
        (cid,"EUR-R",due,500,"EUR",1,"EUR","Açık")
    )
    control_tower.execute(
        """INSERT INTO receivables
        (customer_id,invoice_no,due_date,amount,currency,fx_to_base,base_currency,status)
        VALUES (?,?,?,?,?,?,?,?)""",
        (cid,"GBP-R",due,999,"GBP",1,"GBP","Açık")
    )
    fc = control_tower.cash_forecast("EUR",(30,))
    assert float(fc.iloc[0]["Başlangıç Nakit"]) == 1000
    assert float(fc.iloc[0]["Beklenen Tahsilat"]) == 500
    assert float(fc.iloc[0]["Tahmini Nakit"]) == 1500


def test_certificate_alerts_and_ai_manager(tmp_path):
    db = setup_db(tmp_path)
    control_tower.execute(
        """INSERT INTO compliance_documents
        (owner_type,owner_name,document_type,expiry_date,renewal_lead_days,status)
        VALUES ('Şirket','AS İleri','Health Certificate',?,60,'Geçerli')""",
        (str(date.today()+timedelta(days=15)),)
    )
    alerts = control_tower.certificate_alerts()
    assert alerts.iloc[0]["uyarı"] == "KRİTİK"

    title, df = answer_question(db, "Bugün neye müdahale etmeliyim?")
    assert "önemli" in title.lower()
    assert df is not None
    brief = build_ceo_brief_text(db)
    assert "CEO ÖZETİ" in brief
