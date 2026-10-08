import sys
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import control_tower
from ai_manager import answer_question, build_ceo_brief_text, data_quality_issues, stock_risks


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
    pakmaya_id = id_for("customers", "Pakmaya")

    recs = control_tower.recommendation_rows(product_id=pid)
    assert set(recs["Müşteri"].tolist()) == {"Ülker / Pladis", "Pakmaya"}
    assert pakmaya_id in recs["customer_id"].astype(int).tolist()

    ok, _ = control_tower.create_opportunity_from_recommendation(
        pakmaya_id, pid, 250000, "Serkan"
    )
    assert ok

    recs_after = control_tower.recommendation_rows(product_id=pid)
    assert "Pakmaya" not in recs_after["Müşteri"].tolist()
    assert "Ülker / Pladis" in recs_after["Müşteri"].tolist()
    assert any(
        "Mevcut açık" in d["Neden gösterilmiyor?"]
        for d in recs_after.attrs.get("diagnostics", [])
        if d["Müşteri"] == "Pakmaya"
    )

    ok2, msg2 = control_tower.create_opportunity_from_recommendation(
        pakmaya_id, pid, 250000, "Serkan"
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

    snap_after_partial = control_tower.stock_snapshot()
    prow = snap_after_partial[snap_after_partial["id"] == pid].iloc[0]
    assert float(prow["net_available_kg"]) == 400
    assert float(prow["open_po_kg"]) == 600
    assert float(prow["inbound_kg"]) == 600
    assert float(prow["projected_stock_kg"]) == 1000

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


def test_cancelled_or_over_po_shipment_is_blocked(tmp_path):
    setup_db(tmp_path)
    pid = id_for("product_catalog", "Oat Fibre")
    wid = id_for("warehouses", "Merkez Depo")

    control_tower.execute(
        """INSERT INTO purchase_orders
        (po_number,supplier,product_id,product_name,quantity_kg,unit_price,currency,
         destination_warehouse_id,status)
        VALUES (?,?,?,?,?,?,?,?,?)""",
        ("PO-TEST-OVER","Grainmore",pid,"Oat Fibre",1000,4.3,"EUR",wid,"Sipariş Verildi")
    )
    poid = int(control_tower.query_df(
        "SELECT id FROM purchase_orders WHERE po_number='PO-TEST-OVER'"
    ).iloc[0]["id"])

    control_tower.execute(
        """INSERT INTO shipments
        (purchase_order_id,shipment_ref,quantity_kg,status,destination_warehouse_id)
        VALUES (?,?,?,?,?)""",
        (poid,"CANCELLED",200,"İptal",wid)
    )
    cancelled_id = int(control_tower.query_df(
        "SELECT id FROM shipments WHERE shipment_ref='CANCELLED'"
    ).iloc[0]["id"])
    ok_cancelled, _ = control_tower.receive_shipment_to_stock(cancelled_id)
    assert not ok_cancelled

    control_tower.execute(
        """INSERT INTO shipments
        (purchase_order_id,shipment_ref,quantity_kg,status,destination_warehouse_id)
        VALUES (?,?,?,?,?)""",
        (poid,"FIRST",800,"Yolda",wid)
    )
    first_id = int(control_tower.query_df(
        "SELECT id FROM shipments WHERE shipment_ref='FIRST'"
    ).iloc[0]["id"])
    ok_first, _ = control_tower.receive_shipment_to_stock(first_id)
    assert ok_first

    control_tower.execute(
        """INSERT INTO shipments
        (purchase_order_id,shipment_ref,quantity_kg,status,destination_warehouse_id)
        VALUES (?,?,?,?,?)""",
        (poid,"OVER",300,"Yolda",wid)
    )
    over_id = int(control_tower.query_df(
        "SELECT id FROM shipments WHERE shipment_ref='OVER'"
    ).iloc[0]["id"])
    ok_over, msg_over = control_tower.receive_shipment_to_stock(over_id)
    assert not ok_over
    assert "aşar" in msg_over.lower()


def test_terminal_opportunity_clears_followup_and_auto_tasks(tmp_path):
    setup_db(tmp_path)
    opp = control_tower.query_df(
        "SELECT id,customer_id FROM opportunities WHERE product='Mokaero 22 Topping Base'"
    ).iloc[0]
    opp_id = int(opp["id"])
    customer_name = control_tower.query_df(
        "SELECT name FROM customers WHERE id=?", (int(opp["customer_id"]),)
    ).iloc[0]["name"]

    control_tower.execute(
        """INSERT INTO tasks
        (title,related_to,owner,priority,due_date,status,notes)
        VALUES (?,?,?,?,?,'Açık',?)""",
        (
            "Endüstriyel deneme sonucunu takip et",
            customer_name,
            "Satış",
            "Yüksek",
            str(date.today()+timedelta(days=2)),
            f"Satış pipeline fırsatı #{opp_id}",
        )
    )

    ok, _ = control_tower.update_opportunity_stage(
        opp_id,
        "Kaybedildi",
        0,
        "Eski takip",
        date.today()+timedelta(days=3),
        "Satış",
        date.today()+timedelta(days=30),
        "Fiyat",
        "Müşteri devam etmedi",
    )
    assert ok

    row = control_tower.query_df(
        "SELECT stage,next_action,due_date,lost_reason FROM opportunities WHERE id=?",
        (opp_id,)
    ).iloc[0]
    assert row["stage"] == "Kaybedildi"
    assert row["next_action"] == ""
    assert row["due_date"] == ""
    assert row["lost_reason"] == "Fiyat"

    task_status = control_tower.query_df(
        "SELECT status FROM tasks WHERE notes=?",
        (f"Satış pipeline fırsatı #{opp_id}",)
    ).iloc[0]["status"]
    assert task_status == "Tamamlandı"

    ok2, _ = control_tower.update_opportunity_stage(
        opp_id,
        "Temas",
        20,
        "Tekrar ara",
        date.today()+timedelta(days=2),
        "Satış",
        date.today()+timedelta(days=45),
        "Eski neden kalmamalı",
        "Fırsat yeniden açıldı",
    )
    assert ok2
    reopened = control_tower.query_df(
        "SELECT stage,next_action,lost_reason FROM opportunities WHERE id=?",
        (opp_id,)
    ).iloc[0]
    assert reopened["stage"] == "Temas"
    assert reopened["next_action"] == "Tekrar ara"
    assert reopened["lost_reason"] == ""


def test_data_quality_diagnostics_flag_missing_profiles(tmp_path):
    db = setup_db(tmp_path)
    issues = data_quality_issues(db)
    assert not issues.empty
    assert "Müşteri üretim profili eksik" in issues["Eksik / Risk"].tolist()
    title, df = answer_question(db, "Sistemde hangi kritik veriler eksik?")
    assert "eksik" in title.lower()
    assert df is not None and not df.empty


def test_partial_quality_hold_reduces_only_held_quantity(tmp_path):
    setup_db(tmp_path)
    pid = id_for("product_catalog", "GMS Food Grade")
    wid = id_for("warehouses", "Merkez Depo")
    control_tower.execute(
        """INSERT INTO inventory_lots
        (product_id,product_name,warehouse_id,lot_number,
         quantity_received_kg,quantity_available_kg,quantity_reserved_kg,quality_status)
        VALUES (?,?,?,?,?,?,?,?)""",
        (pid, "GMS Food Grade", wid, "GMS-1", 1000, 1000, 0, "Released")
    )
    lot_id = int(control_tower.query_df(
        "SELECT id FROM inventory_lots WHERE lot_number='GMS-1'"
    ).iloc[0]["id"])

    ok, _ = control_tower.set_lot_quality_status(
        lot_id, "HOLD", 123, hold_kg=300
    )
    assert ok
    snap = control_tower.stock_snapshot()
    row = snap[snap["id"] == pid].iloc[0]
    assert float(row["quality_hold_kg"]) == 300
    assert float(row["net_available_kg"]) == 700

    ok2, _ = control_tower.set_lot_quality_status(lot_id, "Released", None)
    assert ok2
    snap2 = control_tower.stock_snapshot()
    row2 = snap2[snap2["id"] == pid].iloc[0]
    assert float(row2["quality_hold_kg"]) == 0
    assert float(row2["net_available_kg"]) == 1000


def test_ai_stock_risk_respects_open_po(tmp_path):
    db = setup_db(tmp_path)
    pid = id_for("product_catalog", "Vital Wheat Gluten")
    wid = id_for("warehouses", "Merkez Depo")

    control_tower.execute(
        """INSERT INTO inventory_lots
        (product_id,product_name,warehouse_id,lot_number,
         quantity_received_kg,quantity_available_kg,quantity_reserved_kg,quality_status)
        VALUES (?,?,?,?,?,?,?,?)""",
        (pid, "Vital Wheat Gluten", wid, "VG-LOW", 1000, 1000, 0, "Released")
    )
    control_tower.execute(
        """INSERT INTO inventory_policy
        (product_id,monthly_usage_kg,safety_stock_days,lead_time_days,reorder_review_days)
        VALUES (?,?,?,?,?)""",
        (pid, 3000, 30, 30, 7)
    )

    risks_without_po = stock_risks(db)
    assert "Vital Wheat Gluten" in risks_without_po["ürün"].tolist()

    control_tower.execute(
        """INSERT INTO purchase_orders
        (po_number,supplier,product_id,product_name,quantity_kg,unit_price,currency,
         destination_warehouse_id,status)
        VALUES (?,?,?,?,?,?,?,?,?)""",
        ("PO-AI-STOCK","Fidelinka",pid,"Vital Wheat Gluten",10000,1.6,"EUR",wid,"Teyitli")
    )

    risks_with_po = stock_risks(db)
    assert "Vital Wheat Gluten" not in risks_with_po["ürün"].tolist()


def test_weighted_pipeline_excludes_won_deals(tmp_path):
    db = setup_db(tmp_path)
    before = __import__("ai_manager").dashboard_snapshot(db)
    assert before["active_opps"] == 2
    assert round(float(before["weighted"]), 2) == 311000.00

    opp_id = int(control_tower.query_df(
        "SELECT id FROM opportunities WHERE product='Mokaero 22 Topping Base'"
    ).iloc[0]["id"])
    ok, _ = control_tower.update_opportunity_stage(
        opp_id,
        "Kazanıldı",
        100,
        "Bu alan temizlenmeli",
        date.today()+timedelta(days=3),
        "Satış",
        date.today(),
        "",
        "Sipariş kazanıldı",
    )
    assert ok

    after = __import__("ai_manager").dashboard_snapshot(db)
    assert after["active_opps"] == 1
    assert round(float(after["weighted"]), 2) == 245000.00


def test_quote_status_sync_draft_sent_and_acceptance(tmp_path):
    setup_db(tmp_path)
    opp_id = int(control_tower.query_df(
        "SELECT id FROM opportunities WHERE product='Mokaero 22 Topping Base'"
    ).iloc[0]["id"])

    before = control_tower.query_df(
        "SELECT stage FROM opportunities WHERE id=?", (opp_id,)
    ).iloc[0]["stage"]
    assert before == "Deneme"

    ok_draft, _ = control_tower.sync_quote_to_opportunity(
        opp_id, "Taslak", "Satış", "Pakmaya"
    )
    assert ok_draft
    after_draft = control_tower.query_df(
        "SELECT stage FROM opportunities WHERE id=?", (opp_id,)
    ).iloc[0]["stage"]
    assert after_draft == "Deneme"

    ok_sent, _ = control_tower.sync_quote_to_opportunity(
        opp_id, "Gönderildi", "Satış", "Pakmaya"
    )
    assert ok_sent
    after_sent = control_tower.query_df(
        "SELECT stage,next_action FROM opportunities WHERE id=?", (opp_id,)
    ).iloc[0]
    assert after_sent["stage"] == "Teklif"
    assert after_sent["next_action"] == "Teklif takibi"

    ok_accept, _ = control_tower.sync_quote_to_opportunity(
        opp_id, "Kabul", "Satış", "Pakmaya"
    )
    assert ok_accept
    after_accept = control_tower.query_df(
        "SELECT stage,next_action FROM opportunities WHERE id=?", (opp_id,)
    ).iloc[0]
    assert after_accept["stage"] == "Sipariş"
    assert after_accept["next_action"] == "Sipariş teyidi / sevkiyat planı"


def test_revised_quote_does_not_regress_advanced_stage(tmp_path):
    setup_db(tmp_path)
    opp_id = int(control_tower.query_df(
        "SELECT id FROM opportunities WHERE product='Mokaero 22 Topping Base'"
    ).iloc[0]["id"])

    control_tower.update_opportunity_stage(
        opp_id,
        "Pazarlık",
        75,
        "Son fiyat",
        date.today()+timedelta(days=2),
        "Satış",
        date.today()+timedelta(days=20),
        "",
        "İleri aşama",
    )

    ok, _ = control_tower.sync_quote_to_opportunity(
        opp_id, "Revizyon", "Satış", "Pakmaya"
    )
    assert ok
    row = control_tower.query_df(
        "SELECT stage FROM opportunities WHERE id=?", (opp_id,)
    ).iloc[0]
    assert row["stage"] == "Pazarlık"
