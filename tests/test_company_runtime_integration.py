"""Real non-superuser PostgreSQL logins; disposable loopback CI only."""
import json
import os
import unittest
from unittest.mock import patch
from uuid import uuid4

from tests.test_postgres_live_integration import validated_ci_url
from scripts.postgres_live_schema import schema_ddl_steps
from scripts.four_company_foundation_ddl import foundation_ddl
from scripts.company_runtime_schema import runtime_ddl, runtime_role_grants
from scripts.group_company_catalog import COMPANY_LABELS
from scripts import company_runtime as rt


class CompanyRuntimeIntegration(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import psycopg
        cls.url = validated_ci_url()
        cls.conn = psycopg.connect(cls.url, sslmode='disable', autocommit=True)
        cls.roles = ('ct_ci_runtime_alpha', 'ct_ci_runtime_beta', 'ct_ci_runtime_viewer')
        with cls.conn.transaction(), cls.conn.cursor() as cur:
            cur.execute("SELECT to_regnamespace('ct_app')")
            if cur.fetchone()[0] is not None:
                raise RuntimeError('Disposable runtime suite requires an empty database')
            cur.execute('CREATE SCHEMA ct_app')
            cur.execute('SET LOCAL search_path=ct_app,pg_catalog')
            _, ddl, fks = schema_ddl_steps()
            for statement in [*ddl, *fks, *foundation_ddl(), *runtime_ddl()]:
                cur.execute(statement)
            cls.codes = tuple(COMPANY_LABELS)
            for code in cls.codes:
                cur.execute('INSERT INTO ct_app.legal_entities (code,legal_name) VALUES (%s,%s)', (code,'Fictional CI entity'))
            for index, role in enumerate(cls.roles):
                cur.execute('CREATE ROLE '+role+" LOGIN PASSWORD 'runtime-ci-only' NOINHERIT NOSUPERUSER NOBYPASSRLS NOCREATEROLE NOCREATEDB")
                for statement in runtime_role_grants(role):
                    cur.execute(statement)
                principal = ('alpha','beta','observer')[index]
                cur.execute('INSERT INTO ct_app.company_login_bindings VALUES (%s,%s,%s,TRUE)', (principal, role, 'VIEWER' if index == 2 else 'ADMIN'))
                for entity in ([1,3,4] if index == 0 else [2] if index == 1 else [1]):
                    cur.execute('INSERT INTO ct_app.company_read_grants VALUES (%s,%s,TRUE)', (principal,entity))
                    cur.execute('INSERT INTO ct_app.company_write_grants VALUES (%s,%s,%s)', (principal,entity,index!=2))
        cls.accounts = {p: {'role': r, 'url': 'postgresql://'+r+':runtime-ci-only@127.0.0.1:5432/ct_ci_control_tower'} for p,r in zip(('alpha','beta','observer'), cls.roles)}

    @classmethod
    def tearDownClass(cls):
        with cls.conn.transaction(), cls.conn.cursor() as cur:
            cur.execute('DROP SCHEMA ct_app CASCADE')
            for role in cls.roles:
                cur.execute('DROP ROLE '+role)
        cls.conn.close()

    def call(self, operation=None, *, who='alpha', company=0, request=None, section=None, **inputs):
        # Browser identity verification is independently covered by HMAC tests;
        # no DB authentication, policy, query, transaction or role is mocked.
        role = 'VIEWER' if who == 'observer' else 'ADMIN'
        secrets = {'CT_COMPANY_RUNTIME_MODE':rt.WRITE_MODE,
                   'CT_COMPANY_DB_CONNECTIONS_JSON':json.dumps(self.accounts)}
        with patch.object(rt,'_secret',side_effect=lambda k,d='':secrets.get(k,d)), patch.object(rt,'verified_company_principal',return_value=who), patch.object(rt,'current_user',return_value={'role':role}):
            return rt.execute_request({}, self.codes[company], operation=operation, request_id=request or str(uuid4()), inputs=inputs, section=section)

    def ok(self, operation, **inputs):
        status, ident = self.call(operation, **inputs)
        self.assertEqual(status,'ok', operation+': '+status)
        return ident

    def test_core_flow_and_negative_boundaries(self):
        customer = self.ok('create_customer', name='Synthetic customer')
        self.ok('create_contact', customer_id=customer, name='Synthetic contact')
        status, _ = self.call('create_contact', who='beta', company=1, customer_id=customer, name='Cross tenant')
        self.assertEqual(status,'wrong_company_customer')
        warehouse = self.ok('create_warehouse', name='Synthetic warehouse')
        product = self.ok('create_product', name='Synthetic ingredient')
        account = self.ok('create_account', name='Synthetic bank', currency='EUR', opening_balance=1000)
        po = self.ok('create_purchase_order', po_number='CI-100', supplier='Synthetic supplier', product_id=product, warehouse_id=warehouse, quantity_kg=100, unit_price=2, currency='EUR')
        shipment = self.ok('create_shipment', purchase_order_id=po, shipment_ref='CI-SHIP', quantity_kg=100)
        status, _ = self.call('create_shipment', purchase_order_id=po, shipment_ref='OVER', quantity_kg=1)
        self.assertEqual(status,'over_shipment')
        lot = self.ok('receive_shipment', shipment_id=shipment)
        status, _ = self.call('receive_shipment', shipment_id=shipment)
        self.assertEqual(status,'already_received_or_cancelled')
        payable = self.ok('create_payable', purchase_order_id=po, supplier='Synthetic supplier', invoice_no='CI-INV', due_date='2026-12-01', amount=200, currency='EUR')
        self.ok('hold_inventory_lot', lot_id=lot, case_no='CI-Q', hold_kg=20, reason='Synthetic test')
        status, _ = self.call('pay_supplier', payable_id=payable, account_id=account, amount=200, reference='CI-PAY', payment_date='2026-10-12')
        self.assertEqual(status,'quality_hold_blocks_payment')
        self.ok('release_inventory_lot', lot_id=lot, resolution='Synthetic release')
        self.ok('pay_supplier', payable_id=payable, account_id=account, amount=200, reference='CI-PAY', payment_date='2026-10-12')
        receivable = self.ok('create_receivable', customer_id=customer, invoice_no='CI-AR', due_date='2026-12-01', amount=300, currency='EUR')
        self.ok('collect_customer_payment', receivable_id=receivable, account_id=account, amount=300, reference='CI-COL', payment_date='2026-10-12')
        status, report = self.call(section='Yönetici Özeti')
        self.assertEqual(status,'ok')
        self.assertEqual(report['finance_by_currency']['cash'][0]['amount'],1100)
        self.assertEqual(report['finance_by_currency']['payables_open'][0]['amount'],0)
        status, rows = self.call(who='beta', company=1, section='Müşteriler')
        self.assertEqual((status,rows),('ok',[]))
        self.assertEqual(self.call(who='beta', company=0, section='Müşteriler')[0],'forbidden')
        self.assertEqual(self.call('create_customer', who='observer', name='No write')[0],'forbidden')
        # Even raw SQL with no WHERE cannot expose other-company records.
        import psycopg
        with psycopg.connect(self.accounts['beta']['url'],sslmode='disable',autocommit=True) as conn:
            with conn.cursor() as cur:
                cur.execute('SELECT id FROM ct_app.customers')
                self.assertEqual(cur.fetchall(),[])
                with self.assertRaises(psycopg.errors.InsufficientPrivilege):
                    cur.execute("INSERT INTO ct_app.customers (name,legal_entity_id) VALUES ('blocked',1)")
                with self.assertRaises(psycopg.errors.InsufficientPrivilege):
                    cur.execute('UPDATE ct_app.company_write_grants SET can_write=TRUE')
                with self.assertRaises(psycopg.errors.InsufficientPrivilege):
                    cur.execute('SELECT * FROM ct_app.audit_log')
        # Composite FK defends users who legitimately hold both companies.
        with psycopg.connect(self.accounts['alpha']['url'],sslmode='disable',autocommit=True) as conn:
            with conn.cursor() as cur:
                with self.assertRaises(psycopg.errors.ForeignKeyViolation):
                    cur.execute("INSERT INTO ct_app.contacts (customer_id,name,legal_entity_id) VALUES (%s,'blocked',3)", (customer,))
                with self.assertRaises(psycopg.errors.RaiseException):
                    cur.execute('UPDATE ct_app.customers SET legal_entity_id=3 WHERE id=%s', (customer,))

    def test_z_encrypted_native_backup_restore(self):
        from scripts.company_runtime_backup import backup_runtime,restore_disposable
        from urllib.parse import urlsplit,urlunsplit
        import psycopg
        passphrase='synthetic-backup-passphrase-2026'
        status,encrypted=backup_runtime(self.url,passphrase)
        self.assertEqual(status,'encrypted')
        p=urlsplit(self.url)
        target=urlunsplit((p.scheme,p.netloc,'/ct_ci_control_tower_restore','',''))
        with self.conn.cursor() as cur:
            cur.execute('CREATE DATABASE ct_ci_control_tower_restore')
        try:
            self.assertEqual(restore_disposable(encrypted,passphrase,target),'restored')
            with psycopg.connect(target,sslmode='disable') as restored:
                with self.conn.cursor() as source,restored.cursor() as dest:
                    source.execute("SELECT tablename FROM pg_tables WHERE schemaname='ct_app' ORDER BY tablename")
                    tables=[r[0] for r in source.fetchall()]
                    self.assertEqual(len(tables),33)
                    for table in tables:
                        statement='SELECT row_to_json(t)::text FROM ct_app.'+table+' t ORDER BY row_to_json(t)::text'
                        source.execute(statement)
                        dest.execute(statement)
                        self.assertEqual(source.fetchall(),dest.fetchall(),table)
                    dest.execute("SELECT COUNT(*) FROM pg_policies WHERE schemaname='ct_app'")
                    source.execute("SELECT COUNT(*) FROM pg_policies WHERE schemaname='ct_app'")
                    self.assertEqual(dest.fetchone(),source.fetchone())
            # The restored app remains RLS-protected with original restricted roles.
            beta=self.accounts['beta']['url'].replace('/ct_ci_control_tower','/ct_ci_control_tower_restore')
            with psycopg.connect(beta,sslmode='disable') as conn,conn.cursor() as cur:
                cur.execute('SELECT id FROM ct_app.customers')
                self.assertEqual(cur.fetchall(),[])
            self.assertEqual(restore_disposable(encrypted,passphrase,target),'target_not_empty')
        finally:
            with self.conn.cursor() as cur:
                cur.execute('DROP DATABASE ct_ci_control_tower_restore')

    def test_quote_purchase_invoice_collection(self):
        customer = self.ok('create_customer',name='Quote customer',company=2)
        product = self.ok('create_product',name='Quoted ingredient',company=2)
        warehouse = self.ok('create_warehouse',name='Quote warehouse',company=2)
        quote = self.ok('create_quote',company=2,customer_id=customer,product_name='Quoted ingredient',quantity_kg=100,buy_price_per_kg=2,buy_currency='EUR',buy_fx_to_base=1,base_currency='EUR',sell_price_per_kg=3,sell_currency='EUR',sell_fx_to_base=1,freight_total_base=10,annual_finance_rate_pct=10,prepayment_pct=20,prepayment_lead_days=30,stock_days=10,customer_credit_days=60)
        self.ok('purchase_from_quote',company=2,quote_id=quote,po_number='CI-Q-PO',supplier='Supplier Q',product_id=product,warehouse_id=warehouse)
        invoice = self.ok('invoice_quote',company=2,quote_id=quote,invoice_no='CI-Q-INV',due_date='2026-12-01')
        self.assertEqual(self.call('invoice_quote',company=2,quote_id=quote,invoice_no='DUP',due_date='2026-12-01')[0],'quote_unavailable')
        with self.conn.cursor() as cur:
            cur.execute('SELECT amount,quote_id,legal_entity_id FROM ct_app.receivables WHERE id=%s',(invoice,))
            self.assertEqual(cur.fetchone(),(300,quote,3))
            cur.execute('SELECT calculation_snapshot FROM ct_app.quotes WHERE id=%s',(quote,))
            snap = cur.fetchone()[0]
            self.assertEqual(snap['inputs']['prepayment_pct'],20)
            self.assertGreater(float(snap['result']['cost_per_kg_base']),2.1)

    def test_idempotency_and_revocation(self):
        request = str(uuid4())
        a = self.call('create_customer', name='Retry test', request=request)
        b = self.call('create_customer', name='Retry test', request=request)
        self.assertEqual(a[0],'ok')
        self.assertEqual(a,b)
        self.assertEqual(self.call('create_customer', name='Changed request', request=request)[0],'request_conflict')
        with self.conn.cursor() as cur:
            cur.execute("UPDATE ct_app.company_write_grants SET can_write=FALSE WHERE principal_id='alpha' AND legal_entity_id=4")
        self.assertEqual(self.call('create_customer', company=3, name='Revoked')[0],'forbidden')
        with self.conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) FROM ct_app.company_requests WHERE request_id=%s",(request,))
            self.assertEqual(cur.fetchone()[0],1)

    def test_audit_failure_rolls_back_business_record(self):
        # Remove audit INSERT temporarily on disposable role to force late failure.
        with self.conn.cursor() as cur:
            cur.execute('REVOKE INSERT ON ct_app.company_operation_audit FROM ct_ci_runtime_alpha')
        try:
            self.assertEqual(self.call('create_customer', name='Must roll back')[0],'failed')
            with self.conn.cursor() as cur:
                cur.execute("SELECT COUNT(*) FROM ct_app.customers WHERE name='Must roll back'")
                self.assertEqual(cur.fetchone()[0],0)
        finally:
            with self.conn.cursor() as cur:
                cur.execute('GRANT INSERT ON ct_app.company_operation_audit TO ct_ci_runtime_alpha')
