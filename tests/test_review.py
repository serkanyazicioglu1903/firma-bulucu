import tempfile
import unittest
from pathlib import Path
import control_tower as ct
import ai_manager as ai
from sales_matching import matched_sectors, normalize


class ReviewTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.previous = ct.DB_PATH
        ct.DB_PATH = Path(self.temp.name) / 'test.db'
        ct.init_db()
        ct.seed_once()
        ct.seed_product_catalog()
        ct.seed_warehouses()

    def tearDown(self):
        ct.DB_PATH = self.previous
        self.temp.cleanup()

    def test_sector_aliases_and_word_boundaries(self):
        self.assertTrue(matched_sectors('BİSKÜVİ / Unlu Mamul', 'fırıncılık;bakery'))
        self.assertEqual(len(matched_sectors('bakery fırıncılık', 'bakery;fırıncılık')), 1)
        self.assertFalse(matched_sectors('market / paket', 'et;meat'))
        self.assertEqual(normalize('İÇECEK'), normalize('içecek'))

    def test_fat_powder_and_exclusion_explanation(self):
        r = ct.recommendation_rows(product_id=3)
        self.assertEqual(set(r['Müşteri']), {'Ülker / Pladis', 'Pakmaya'})
        ok, _ = ct.create_opportunity_from_recommendation(1, 3, 100, 'Test')
        self.assertTrue(ok)
        self.assertFalse(ct.create_opportunity_from_recommendation(1, 3, 100, 'Test')[0])
        r = ct.recommendation_rows(product_id=3)
        self.assertEqual(set(r['Müşteri']), {'Pakmaya'})
        self.assertIn('Mevcut açık', r.attrs['diagnostics'][0]['Neden gösterilmiyor?'])
        ct.save_customer_product_status(2,3,'Uygun Değil','',0,'test')
        self.assertTrue(ct.recommendation_rows(product_id=3).empty)

    def test_quote_financing_and_margin(self):
        q = ct.calculate_quote(1000,2,1,100,0,0,0,0,36.5,10,30,60,3,1,0,20)
        self.assertAlmostEqual(q['total_cost_base'],2310)
        self.assertAlmostEqual(q['profit_total_base'],690)
        self.assertAlmostEqual(q['required_sell_price'],2.8875)

    def test_payments_reject_wrong_account_without_mutating(self):
        ct.execute("INSERT INTO cash_accounts(name,currency,balance) VALUES ('GBP bank','GBP',1000)")
        ct.execute("INSERT INTO cash_accounts(name,currency,balance) VALUES ('EUR bank','EUR',1000)")
        ct.execute("INSERT INTO receivables(customer_id,due_date,amount,currency) VALUES (1,'2026-10-01',100,'EUR')")
        ct.execute("INSERT INTO payables(supplier,due_date,amount,currency) VALUES ('Test','2026-10-01',100,'EUR')")
        for table, func in [('receivables',ct.record_receivable_payment),('payables',ct.record_payable_payment)]:
            self.assertFalse(func(1,40,'2026-10-07',1,'','')[0])
            self.assertFalse(func(1,40,'2026-10-07',999,'','')[0])
            self.assertEqual(ct.query_df(f'SELECT paid_amount FROM {table}').iloc[0,0],0)
            self.assertTrue(func(1,40,'2026-10-07',2,'','')[0])
            self.assertFalse(func(1,61,'2026-10-07',2,'','')[0])
        self.assertEqual(ct.query_df('SELECT balance FROM cash_accounts WHERE id=2').iloc[0,0],1000)

    def test_stock_receipt_once_and_cancel_guard(self):
        ct.execute("INSERT INTO purchase_orders(po_number,supplier,product_name,quantity_kg,destination_warehouse_id) VALUES ('TEST-001','Test','Test',100,1)")
        ct.execute("INSERT INTO shipments(purchase_order_id,quantity_kg,status) VALUES (1,100,'İptal')")
        self.assertFalse(ct.receive_shipment_to_stock(1)[0])
        ct.execute("UPDATE shipments SET status='Planlandı' WHERE id=1")
        self.assertTrue(ct.receive_shipment_to_stock(1)[0])
        self.assertFalse(ct.receive_shipment_to_stock(1)[0])
        self.assertEqual(ct.query_df('SELECT SUM(quantity_available_kg) FROM inventory_lots').iloc[0,0],100)

    def test_currency_totals_do_not_mix(self):
        before=ai.dashboard_snapshot(ct.DB_PATH)['weighted']
        ct.execute("INSERT INTO opportunities(customer_id,product,value,currency,probability) VALUES (1,'Test',1000,'GBP',100)")
        self.assertEqual(ai.dashboard_snapshot(ct.DB_PATH)['weighted'],before)
        totals=ct.opportunity_totals(weighted=True)
        self.assertIn('GBP',totals)
        self.assertIn('EUR',totals)

    def test_read_models_and_manager(self):
        for f in [ct.stock_snapshot,ct.outstanding_receivables,ct.outstanding_payables,ct.cash_forecast,ct.quality_case_summary,ct.certificate_alerts,ct.regulatory_alerts]:
            f()
        for q in ['bugün','nakit','stok','marj','kalite','unutulan','satış','risk']:
            ai.answer_question(ct.DB_PATH,q)
        self.assertIn('CEO ÖZETİ',ai.build_ceo_brief_text(ct.DB_PATH))


if __name__ == '__main__':
    unittest.main()
