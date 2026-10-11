"""Real PostgreSQL transaction test using a disposable GitHub Actions service.

NEVER connects to Supabase: strict loopback, database-name, username and
explicit CI toggle are checked before creating ANY schema or data. The service
database is destroyed by GitHub Actions after the job. Production SSL is still
required everywhere except this deliberately restricted local Docker test.
"""
import os
from decimal import Decimal
from urllib.parse import urlsplit
import unittest

from scripts.build_pg_schema import quote
from scripts.postgres_connection import sslmode_for, CI_DATABASE, CI_USER
from scripts.postgres_live_schema import schema_ddl_steps
from scripts.staging_validate import validate_staging_structure
from scripts.postgres_operational_write import (
    create_customer, create_product, create_warehouse, create_purchase_order, create_shipment,
    receive_shipment, hold_inventory_lot, release_inventory_lot,
    create_payable, pay_supplier,
)
from scripts.postgres_operational_read import read_operational_counts, read_operational_workspace


def validated_ci_url():
    url = os.environ.get("CT_TEST_DATABASE_URL", "")
    try:
        parsed = urlsplit(url)
        allowed = (
            os.environ.get("CT_LOCAL_POSTGRES_TEST") == "1"
            and os.environ.get("AS_CONTROL_TOWER_PG_WRITES_ENABLED") == "1"
            and parsed.scheme in ("postgres", "postgresql")
            and parsed.hostname in ("127.0.0.1", "localhost")
            and parsed.port == 5432
            and parsed.username == CI_USER
            and parsed.path == "/" + CI_DATABASE
            and sslmode_for(url) == "disable"
        )
    except ValueError:
        allowed = False
    if not allowed:
        raise unittest.SkipTest("Only the local, disposable CI PostgreSQL database is permitted.")
    return url


class RealPostgresOperationalIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.url = validated_ci_url()
        import psycopg
        cls.conn = psycopg.connect(
            cls.url, sslmode=sslmode_for(cls.url), connect_timeout=8,
            autocommit=True,
        )
        tables, ddl, foreign_keys = schema_ddl_steps()
        if len(tables) != 26:
            raise AssertionError("Expected 26 tables")
        with cls.conn.transaction():
            with cls.conn.cursor() as cur:
                # Never DROP/modify an existing schema, even in CI.
                cur.execute(
                    "SELECT EXISTS (SELECT 1 FROM pg_namespace WHERE nspname=%s)",
                    ("ct_app",),
                )
                if cur.fetchone()[0]:
                    raise AssertionError("ct_app already exists; refusing to touch data.")
                cur.execute('CREATE SCHEMA "ct_app"')
                cur.execute('SET LOCAL search_path TO "ct_app", pg_catalog')
                for statement in ddl + foreign_keys:
                    cur.execute(statement)
        status, issues = validate_staging_structure(cls.url, schema="ct_app")
        if status != "ok":
            raise AssertionError("Live ct_app schema failed its structural check.")
 
    @classmethod
    def tearDownClass(cls):
        if hasattr(cls, "conn"):
            cls.conn.close()

    def execute(self, sql, parameters=()):
        with self.conn.cursor() as cur:
            cur.execute(sql, parameters)
            if sql.lstrip().upper().startswith("SELECT"):
                return cur.fetchone()
            return None

    def test_two_company_readiness_gate_on_disposable_postgres(self):
        """Schema review never certifies entity isolation or writes records."""
        from scripts.postgres_company_scope import assess_company_scope
        from scripts.postgres_acceptance import evaluate_acceptance

        with self.conn.cursor() as cur:
            cur.execute('SELECT COUNT(*) FROM "ct_app"."audit_log"')
            before = cur.fetchone()[0]
        review = assess_company_scope(self.url)
        self.assertEqual(review["status"], "review_required")
        self.assertEqual(review["checked_count"], 8)
        self.assertEqual(len(review["without_direct_entity"]), 8)
        self.assertFalse(review["isolation_verified"])

        acceptance = evaluate_acceptance(self.url)
        self.assertIn(acceptance["status"], ("review_required", "critical_issues"))
        self.assertIn("Tüzel kişi ayrımı", acceptance["external_gates"][0])
        with self.conn.cursor() as cur:
            cur.execute('SELECT COUNT(*) FROM "ct_app"."audit_log"')
            self.assertEqual(cur.fetchone()[0], before)

    def test_legal_entity_constraints_rehearsed_then_rolled_back(self):
        """Four fictional entities, real FK checks, disposable CI only.

        Even in CI, rollback BOTH schema and dummy data before other tests.
        Never guess existing row ownership in a production database.
        """
        from scripts.postgres_legal_entity_rehearsal import (
            additive_ddl, enforcement_ddl,
        )
        from scripts.postgres_company_scope import CRITICAL_TABLES
        from scripts.postgres_company_migration_guard import (
            company_schema_status_on_cursor,
        )
        import psycopg

        class IntentionallyRollback(Exception):
            pass

        try:
            with self.conn.transaction():
                with self.conn.cursor() as cur:
                    self.assertEqual(
                        company_schema_status_on_cursor(cur),
                        "legacy_schema_only",
                    )
                    for stmt in additive_ddl():
                        cur.execute(stmt)
                    self.assertEqual(
                        company_schema_status_on_cursor(cur),
                        "partial_company_schema",
                    )
                    cur.execute(
                        'INSERT INTO "ct_app"."legal_entities" (code,legal_name) '
                        "VALUES ('CI_A','Fictional CI Company A'), "
                        "('CI_B','Fictional CI Company B'), "
                        "('CI_C','Fictional CI Company C'), "
                        "('CI_D','Fictional CI Company D') RETURNING id"
                    )
                    # ID assignments exist *only inside this transaction*.
                    cur.execute(
                        'SELECT id,code FROM "ct_app"."legal_entities" ORDER BY code'
                    )
                    ids = {code: int(entity_id) for entity_id, code in cur.fetchall()}
                    self.assertEqual(set(ids), {"CI_A", "CI_B", "CI_C", "CI_D"})
                    for table in CRITICAL_TABLES:
                        cur.execute(
                            f'UPDATE "ct_app"."{table}" '
                            'SET legal_entity_id=%s WHERE legal_entity_id IS NULL',
                            (ids["CI_A"],),
                        )
                    for stmt in enforcement_ddl():
                        cur.execute(stmt)

                    for key in ("CI_A", "CI_B", "CI_C", "CI_D"):
                        cur.execute(
                            'INSERT INTO "ct_app"."purchase_orders" '
                            '(po_number,supplier,product_name,legal_entity_id) '
                            'VALUES (%s,%s,%s,%s) RETURNING id',
                            (f"CI-OWNED-{key}", "CI SYNTHETIC SUPPLIER",
                             "CI SYNTHETIC PRODUCT", ids[key]),
                        )
                        ids[key + "_po"] = int(cur.fetchone()[0])

                    # Every company may ship its own PO but never another's.
                    for key in ("CI_A", "CI_B", "CI_C", "CI_D"):
                        cur.execute(
                            'INSERT INTO "ct_app"."shipments" '
                            '(purchase_order_id,shipment_ref,legal_entity_id) '
                            'VALUES (%s,%s,%s)',
                            (ids[key + "_po"], f"CI VALID {key}", ids[key]),
                        )
                    for owner, foreign in (
                        ("CI_B", "CI_A"), ("CI_C", "CI_B"),
                        ("CI_D", "CI_C"), ("CI_A", "CI_D"),
                    ):
                        cur.execute("SAVEPOINT reject_cross_company")
                        with self.assertRaises(psycopg.errors.ForeignKeyViolation):
                            cur.execute(
                                'INSERT INTO "ct_app"."shipments" '
                                '(purchase_order_id,shipment_ref,legal_entity_id) '
                                'VALUES (%s,%s,%s)',
                                (ids[foreign + "_po"], f"CI WRONG {owner}",
                                 ids[owner]),
                            )
                        cur.execute("ROLLBACK TO SAVEPOINT reject_cross_company")
                        cur.execute("RELEASE SAVEPOINT reject_cross_company")

                    # A UK/holding/Planet cash account must not be linked
                    # to an unrelated entity's finance transaction.
                    for key in ("CI_A", "CI_B", "CI_C", "CI_D"):
                        cur.execute(
                            'INSERT INTO "ct_app"."cash_accounts" '
                            '(name,currency,legal_entity_id) VALUES (%s,%s,%s) '
                            'RETURNING id',
                            (f"CI BANK {key}", "EUR", ids[key]),
                        )
                        ids[key + "_bank"] = int(cur.fetchone()[0])
                        cur.execute(
                            'INSERT INTO "ct_app"."finance_transactions" '
                            '(transaction_type,transaction_date,amount,currency,'
                            'account_id,legal_entity_id) VALUES (%s,%s,%s,%s,%s,%s)',
                            ("CI_SYNTHETIC", "2026-10-11", 1, "EUR",
                             ids[key + "_bank"], ids[key]),
                        )
                    cur.execute("SAVEPOINT reject_finance_cross_company")
                    with self.assertRaises(psycopg.errors.ForeignKeyViolation):
                        cur.execute(
                            'INSERT INTO "ct_app"."finance_transactions" '
                            '(transaction_type,transaction_date,amount,currency,'
                            'account_id,legal_entity_id) VALUES (%s,%s,%s,%s,%s,%s)',
                            ("CI_SYNTHETIC", "2026-10-11", 1, "EUR",
                             ids["CI_A_bank"], ids["CI_D"]),
                        )
                    cur.execute("ROLLBACK TO SAVEPOINT reject_finance_cross_company")
                    cur.execute("RELEASE SAVEPOINT reject_finance_cross_company")

                    # Ownerless financial rows must fail after enforcement.
                    cur.execute("SAVEPOINT reject_ownerless")
                    with self.assertRaises(psycopg.errors.NotNullViolation):
                        cur.execute(
                            'INSERT INTO "ct_app"."cash_accounts" '
                            '(name,currency) VALUES (%s,%s)',
                            ("CI OWNERLESS BANK", "EUR"),
                        )
                    cur.execute("ROLLBACK TO SAVEPOINT reject_ownerless")
                    cur.execute("RELEASE SAVEPOINT reject_ownerless")

                    # Test-only DB grants: never map a real user or seed
                    # these permissions into production.
                    from scripts.group_company_catalog import COMPANY_LABELS
                    from scripts.postgres_scoped_company_read import (
                        grant_table_rehearsal_ddl, read_company_records_on_cursor,
                    )
                    for stmt in grant_table_rehearsal_ddl():
                        cur.execute(stmt)
                    group_codes = tuple(COMPANY_LABELS)
                    fictional_ids = ("CI_A", "CI_B", "CI_C", "CI_D")
                    for key, company_code in zip(fictional_ids, group_codes):
                        cur.execute(
                            'UPDATE "ct_app"."legal_entities" SET code=%s WHERE id=%s',
                            (company_code, ids[key]),
                        )
                    # Grant only companies A and D to a fictional reader.
                    for key in ("CI_A", "CI_D"):
                        cur.execute(
                            'INSERT INTO "ct_app"."company_read_grants" '
                            '(principal_id,legal_entity_id,can_read) '
                            'VALUES (%s,%s,TRUE)',
                            ("ci-scoped-reader", ids[key]),
                        )
                    # A viewer of one company must not see B or C ledgers.
                    for code in (group_codes[1], group_codes[2]):
                        for workspace in ("Satın Alma", "Banka / Kasa",
                                          "Finans Hareketleri"):
                            result, rows = read_company_records_on_cursor(
                                cur, "ci-scoped-reader", code, workspace
                            )
                            self.assertEqual((result, rows), ("forbidden", []))
                    for key, code in (("CI_A", group_codes[0]),
                                      ("CI_D", group_codes[3])):
                        result, rows = read_company_records_on_cursor(
                            cur, "ci-scoped-reader", code, "Satın Alma"
                        )
                        self.assertEqual(result, "ok")
                        # Earlier synthetic CI tests may have already created
                        # additional A-owned records; cardinality != 1 is OK.
                        self.assertIn(
                            ids[key + "_po"], {row["id"] for row in rows}
                        )
                        for row in rows:
                            cur.execute(
                                'SELECT legal_entity_id FROM "ct_app"."purchase_orders" '
                                'WHERE id=%s', (row["id"],),
                            )
                            self.assertEqual(cur.fetchone()[0], ids[key])
                        result, rows = read_company_records_on_cursor(
                            cur, "ci-scoped-reader", code, "Banka / Kasa"
                        )
                        self.assertEqual(result, "ok")
                        self.assertIn(
                            ids[key + "_bank"], {row["id"] for row in rows}
                        )
                        for row in rows:
                            cur.execute(
                                'SELECT legal_entity_id FROM "ct_app"."cash_accounts" '
                                'WHERE id=%s', (row["id"],),
                            )
                            self.assertEqual(cur.fetchone()[0], ids[key])
                        result, rows = read_company_records_on_cursor(
                            cur, "ci-scoped-reader", code, "Finans Hareketleri"
                        )
                        self.assertEqual(result, "ok")
                        self.assertTrue(any(row["amount"] == 1 for row in rows))
                        for row in rows:
                            cur.execute(
                                'SELECT legal_entity_id FROM "ct_app"."finance_transactions" '
                                'WHERE id=%s', (row["id"],),
                            )
                            self.assertEqual(cur.fetchone()[0], ids[key])
                    # Verified aggregate KPI: per-company counts and
                    # balances, never leaking bank/PO data from B or C.
                    from scripts.postgres_company_executive_snapshot import (
                        company_executive_snapshot_on_cursor,
                    )
                    for forbidden_code in (group_codes[1], group_codes[2]):
                        status, payload = company_executive_snapshot_on_cursor(
                            cur, "ci-scoped-reader", forbidden_code
                        )
                        self.assertEqual((status, payload), ("forbidden", {}))
                    for key, code in (("CI_A", group_codes[0]),
                                      ("CI_D", group_codes[3])):
                        status, overview = company_executive_snapshot_on_cursor(
                            cur, "ci-scoped-reader", code
                        )
                        self.assertEqual(status, "ok")
                        self.assertFalse(overview["consolidation_verified"])
                        self.assertFalse(overview["cross_company_totals"])
                        cur.execute(
                            'SELECT COUNT(*) FROM "ct_app"."cash_accounts" '
                            'WHERE legal_entity_id=%s', (ids[key],),
                        )
                        self.assertEqual(
                            overview["counts"]["cash_accounts"],
                            cur.fetchone()[0],
                        )
                        cur.execute(
                            'SELECT COUNT(*) FROM "ct_app"."purchase_orders" '
                            'WHERE legal_entity_id=%s', (ids[key],),
                        )
                        self.assertEqual(
                            overview["counts"]["purchase_orders"],
                            cur.fetchone()[0],
                        )
                        self.assertTrue(
                            any(
                                line["currency"] == "EUR"
                                for line in overview["finance_by_currency"]["cash"]
                            )
                        )
                    # Currency is a dimension, not an implied conversion.
                    cur.execute(
                        'INSERT INTO "ct_app"."cash_accounts" '
                        '(name,currency,balance,legal_entity_id) VALUES (%s,%s,%s,%s)',
                        ("CI D ONLY GBP", "GBP", 300, ids["CI_D"]),
                    )
                    status, overview = company_executive_snapshot_on_cursor(
                        cur, "ci-scoped-reader", group_codes[3]
                    )
                    self.assertEqual(status, "ok")
                    self.assertIn(
                        "GBP",
                        {row["currency"] for row in
                         overview["finance_by_currency"]["cash"]},
                    )
                    self.assertIn(
                        "EUR",
                        {row["currency"] for row in
                         overview["finance_by_currency"]["cash"]},
                    )
                    self.assertNotIn(
                        "total_converted", overview
                    )
                    # CI-ONLY atomic writes with exact entity/role grants;
                    # every DDL and fictional row is rolled back below.
                    from scripts.postgres_scoped_company_write_rehearsal import (
                        ScopedWriteDenied, rehearsal_extra_ddl,
                        run_scoped_write_on_cursor,
                    )
                    for statement in rehearsal_extra_ddl():
                        cur.execute(statement)
                    self.assertEqual(
                        company_schema_status_on_cursor(cur),
                        "company_schema_present",
                    )
                    cur.execute(
                        'INSERT INTO "ct_app"."product_catalog" '
                        '(name,supplier) VALUES (%s,%s) RETURNING id',
                        ("CI SHARED ATOMIC WRITE PRODUCT","CI VENDOR"),
                    )
                    shared_product_id = int(cur.fetchone()[0])
                    scoped_purchases = {}
                    scoped_shipments = {}
                    scoped_payables = {}
                    scoped_bank_warehouses = {}
                    for key, company_code in (("CI_A", group_codes[0]),
                                              ("CI_D", group_codes[3])):
                        cur.execute(
                            'INSERT INTO "ct_app"."warehouses" '
                            '(name,city) VALUES (%s,%s) RETURNING id',
                            (f"CI OWNED DEPOT {key}", "CI City"),
                        )
                        warehouse_id = int(cur.fetchone()[0])
                        scoped_bank_warehouses[key] = warehouse_id
                        cur.execute(
                            'INSERT INTO "ct_app"."company_warehouse_scope" '
                            '(warehouse_id,legal_entity_id) VALUES (%s,%s)',
                            (warehouse_id,ids[key]),
                        )
                        cur.execute(
                            'INSERT INTO "ct_app"."company_write_grants" '
                            '(principal_id,legal_entity_id,can_write) '
                            'VALUES (%s,%s,TRUE)',
                            ("ci-scoped-reader",ids[key]),
                        )
                        po = run_scoped_write_on_cursor(
                            cur,"ci-scoped-reader",company_code,"PURCHASING",
                            "create_purchase_order",
                            po_number=f"CI ATOMIC PO {key}",
                            supplier="CI VENDOR",
                            product_id=shared_product_id,
                            warehouse_id=warehouse_id,
                            quantity_kg=10,
                            unit_price=3,
                            currency="EUR",
                        )
                        scoped_purchases[key] = po
                        shipment = run_scoped_write_on_cursor(
                            cur,"ci-scoped-reader",company_code,"PURCHASING",
                            "create_shipment", purchase_order_id=po,
                            shipment_ref=f"CI ATOMIC SHIPMENT {key}",
                            quantity_kg=7,
                        )
                        scoped_shipments[key] = shipment
                        payable = run_scoped_write_on_cursor(
                            cur,"ci-scoped-reader",company_code,"FINANCE",
                            "create_payable",purchase_order_id=po,
                            supplier="CI VENDOR",
                            invoice_no=f"CI ATOMIC INVOICE {key}",
                            due_date="2026-12-01",
                            amount=21,
                            currency="EUR",
                        )
                        scoped_payables[key] = payable
                        for table, ident in (
                            ("purchase_orders",po),("shipments",shipment),
                            ("payables",payable)
                        ):
                            cur.execute(
                                f'SELECT legal_entity_id FROM "ct_app"."{table}" '
                                'WHERE id=%s',(ident,),
                            )
                            self.assertEqual(cur.fetchone()[0], ids[key])
                        cur.execute(
                            'SELECT count(*) FROM "ct_app"."company_operation_audit" '
                            'WHERE principal_id=%s AND legal_entity_id=%s',
                            ("ci-scoped-reader",ids[key]),
                        )
                        self.assertEqual(cur.fetchone()[0],3)

                    # Four-company stock, QA, payment and collection test:
                    # only synthetic owned data and inside the same rollback.
                    cur.execute(
                        'INSERT INTO "ct_app"."customers" (name) VALUES (%s) '
                        'RETURNING id',
                        ("CI FOUR COMPANY PAYMENTS CUSTOMER",),
                    )
                    payment_customer_id = int(cur.fetchone()[0])
                    for company_key, company_code in (
                        ("CI_A",group_codes[0]), ("CI_D",group_codes[3])
                    ):
                        other_key = "CI_D" if company_key == "CI_A" else "CI_A"
                        cur.execute(
                            'UPDATE "ct_app"."cash_accounts" SET balance=%s '
                            'WHERE id=%s AND legal_entity_id=%s',
                            (1000,ids[company_key+"_bank"],ids[company_key]),
                        )
                        cur.execute(
                            'INSERT INTO "ct_app"."receivables" '
                            '(customer_id,due_date,amount,currency,legal_entity_id) '
                            'VALUES (%s,%s,%s,%s,%s) RETURNING id',
                            (payment_customer_id,"2026-12-01",60,"EUR",
                             ids[company_key]),
                        )
                        ar_id=int(cur.fetchone()[0])
                        if company_key == "CI_A":
                            receivable_A=ar_id
                        else:
                            receivable_D=ar_id
                        lot_id = run_scoped_write_on_cursor(
                            cur,"ci-scoped-reader",company_code,"PURCHASING",
                            "receive_shipment",
                            shipment_id=scoped_shipments[company_key],
                        )
                        cur.execute(
                            'SELECT legal_entity_id,quantity_available_kg '
                            'FROM "ct_app"."inventory_lots" WHERE id=%s',
                            (lot_id,),
                        )
                        lot_owner, lot_qty = cur.fetchone()
                        self.assertEqual(lot_owner,ids[company_key])
                        self.assertEqual(lot_qty,7)
                        self.assertEqual(
                            cur.execute(
                                'SELECT 1 FROM "ct_app"."inventory_lots" '
                                'WHERE shipment_id=%s AND legal_entity_id=%s',
                                (scoped_shipments[company_key],ids[other_key]),
                            ).fetchone(),
                            None,
                        )
                        qa_id=run_scoped_write_on_cursor(
                            cur,"ci-scoped-reader",company_code,"QUALITY",
                            "hold_inventory_lot",lot_id=lot_id,
                            case_no=f"CI FOUR COMPANY QA {company_key}",
                            hold_kg=3,reason="CI fictional quality claim",
                        )
                        with self.assertRaises(ScopedWriteDenied) as blocked:
                            run_scoped_write_on_cursor(
                                cur,"ci-scoped-reader",company_code,"FINANCE",
                                "pay_supplier",
                                payable_id=scoped_payables[company_key],
                                account_id=ids[company_key+"_bank"],
                                amount=10,reference=f"CI PAY {company_key}",
                                payment_date="2026-10-11",
                            )
                        self.assertEqual(blocked.exception.code,
                                         "quality_hold_blocks_payment")
                        resolved_id=run_scoped_write_on_cursor(
                            cur,"ci-scoped-reader",company_code,"QUALITY",
                            "release_inventory_lot",lot_id=lot_id,
                            resolution="CI quality cleared",
                        )
                        self.assertEqual(resolved_id,qa_id)
                        pay_id=run_scoped_write_on_cursor(
                            cur,"ci-scoped-reader",company_code,"FINANCE",
                            "pay_supplier",
                            payable_id=scoped_payables[company_key],
                            account_id=ids[company_key+"_bank"],
                            amount=10,reference=f"CI PAY {company_key}",
                            payment_date="2026-10-11",
                        )
                        incoming_id=run_scoped_write_on_cursor(
                            cur,"ci-scoped-reader",company_code,"FINANCE",
                            "collect_customer_payment",receivable_id=ar_id,
                            account_id=ids[company_key+"_bank"],
                            amount=12,reference=f"CI RECEIVE {company_key}",
                            payment_date="2026-10-11",
                        )
                        for txn_id in (pay_id,incoming_id):
                            cur.execute(
                                'SELECT legal_entity_id FROM '
                                '"ct_app"."finance_transactions" WHERE id=%s',
                                (txn_id,),
                            )
                            self.assertEqual(cur.fetchone()[0],ids[company_key])
                        cur.execute(
                            'SELECT balance FROM "ct_app"."cash_accounts" '
                            'WHERE id=%s AND legal_entity_id=%s',
                            (ids[company_key+"_bank"],ids[company_key]),
                        )
                        self.assertEqual(cur.fetchone()[0],1002)
                        cur.execute(
                            'SELECT legal_entity_id,status FROM '
                            '"ct_app"."quality_cases" WHERE id=%s',
                            (qa_id,),
                        )
                        self.assertEqual(cur.fetchone(),(ids[company_key],"Kapandı"))
                        cur.execute(
                            'SELECT count(*) FROM "ct_app"."company_operation_audit" '
                            'WHERE principal_id=%s AND legal_entity_id=%s',
                            ("ci-scoped-reader",ids[company_key]),
                        )
                        self.assertEqual(cur.fetchone()[0],8)

                    # Cross-company documents/banks/lots cannot be reused.
                    company_a=group_codes[0]
                    rejected_operations=(
                        ("receive_shipment",dict(shipment_id=scoped_shipments["CI_D"])),
                        ("hold_inventory_lot",dict(
                            lot_id=lot_id,case_no="CI WRONG QA",hold_kg=1,
                            reason="CI wrong owner")),
                        ("release_inventory_lot",dict(
                            lot_id=lot_id,resolution="CI wrong company")),
                        ("pay_supplier",dict(
                            payable_id=scoped_payables["CI_D"],
                            account_id=ids["CI_A_bank"],
                            amount=1,reference="CI WRONG AP",payment_date="2026-10-11")),
                        ("pay_supplier",dict(
                            payable_id=scoped_payables["CI_A"],
                            account_id=ids["CI_D_bank"],
                            amount=1,reference="CI WRONG BANK",payment_date="2026-10-11")),
                        ("collect_customer_payment",dict(
                            receivable_id=receivable_D,
                            account_id=ids["CI_A_bank"],amount=1,
                            reference="CI WRONG AR",payment_date="2026-10-11")),
                        ("collect_customer_payment",dict(
                            receivable_id=receivable_A,
                            account_id=ids["CI_D_bank"],amount=1,
                            reference="CI WRONG INCOME BANK",
                            payment_date="2026-10-11")),
                    )
                    for action,inputs in rejected_operations:
                        with self.subTest(rejected_action=action,inputs=inputs):
                            with self.assertRaises(ScopedWriteDenied):
                                run_scoped_write_on_cursor(
                                    cur,"ci-scoped-reader",company_a,
                                    "ADMIN",action,**inputs,
                                )
                    with self.assertRaises(ScopedWriteDenied) as duplicate:
                        run_scoped_write_on_cursor(
                            cur,"ci-scoped-reader",company_a,"FINANCE",
                            "pay_supplier",payable_id=scoped_payables["CI_A"],
                            account_id=ids["CI_A_bank"],amount=1,
                            reference="CI PAY CI_A",payment_date="2026-10-11",
                        )
                    self.assertEqual(duplicate.exception.code,"duplicate_payment")
                    cur.execute(
                        'SELECT count(*) FROM "ct_app"."company_operation_audit" '
                        'WHERE principal_id=%s', ("ci-scoped-reader",),
                    )
                    self.assertEqual(cur.fetchone()[0],16)
                    # Wrong tenant and wrong warehouse are denied before INSERT.
                    for target_code in (group_codes[1],group_codes[2]):
                        with self.assertRaises(ScopedWriteDenied):
                            run_scoped_write_on_cursor(
                                cur,"ci-scoped-reader",target_code,"PURCHASING",
                                "create_shipment",
                                purchase_order_id=scoped_purchases["CI_A"],
                                shipment_ref="CI REJECTED SHIPMENT",
                                quantity_kg=1,
                            )
                    for payload in (
                        ("create_shipment", dict(
                            purchase_order_id=scoped_purchases["CI_D"],
                            shipment_ref="CI WRONG COMPANY SHIPMENT",
                            quantity_kg=1)),
                        ("create_payable",dict(
                            purchase_order_id=scoped_purchases["CI_D"],
                            supplier="CI VENDOR",invoice_no="CI WRONG COMPANY INVOICE",
                            due_date="2026-12-01",amount=10,currency="EUR")),
                        ("create_purchase_order",dict(
                            po_number="CI WRONG WAREHOUSE",supplier="CI VENDOR",
                            product_id=shared_product_id,
                            warehouse_id=scoped_bank_warehouses["CI_D"],
                            quantity_kg=10,unit_price=1,currency="EUR")),
                    ):
                        operation, params = payload
                        with self.assertRaises(ScopedWriteDenied):
                            run_scoped_write_on_cursor(
                                cur,"ci-scoped-reader",group_codes[0],
                                "ADMIN",operation,**params,
                            )
                    with self.assertRaises(ScopedWriteDenied):
                        run_scoped_write_on_cursor(
                            cur,"ci-scoped-reader",group_codes[0],
                            "VIEWER","create_purchase_order",
                            po_number="CI VIEWER DENIED",supplier="CI VENDOR",
                            product_id=shared_product_id,
                            warehouse_id=scoped_bank_warehouses["CI_A"],
                            quantity_kg=10,unit_price=1,currency="EUR",
                        )
                    # Removing write access blocks NEW writes even while
                    # read access remains; the prior three operations remain.
                    cur.execute(
                        'UPDATE "ct_app"."company_write_grants" SET can_write=FALSE '
                        'WHERE principal_id=%s AND legal_entity_id=%s',
                        ("ci-scoped-reader",ids["CI_A"]),
                    )
                    with self.assertRaises(ScopedWriteDenied):
                        run_scoped_write_on_cursor(
                            cur,"ci-scoped-reader",group_codes[0],
                            "PURCHASING","create_shipment",
                            purchase_order_id=scoped_purchases["CI_A"],
                            shipment_ref="CI REVOKED WRITE",
                            quantity_kg=1,
                        )
                    cur.execute(
                        'SELECT count(*) FROM "ct_app"."company_operation_audit" '
                        'WHERE principal_id=%s',
                        ("ci-scoped-reader",),
                    )
                    self.assertEqual(cur.fetchone()[0],16)

                    # Real PostgreSQL owner graph is READ-ONLY and uses
                    # only IDs/FKs/row hashes. These CI entities have synthetic
                    # ownership assigned earlier INSIDE THIS ROLLBACK TEST.
                    # NEVER derive a production manifest from owner fields.
                    from scripts.postgres_company_owner_mapping_preflight import (
                        read_owner_graph_on_cursor, snapshot_digest,
                        evaluate_owner_mapping,
                    )
                    graph = read_owner_graph_on_cursor(cur)
                    self.assertEqual(len(graph), 8)
                    synthetic_owner_codes = {
                        ids["CI_A"]: group_codes[0],
                        ids["CI_B"]: group_codes[1],
                        ids["CI_C"]: group_codes[2],
                        ids["CI_D"]: group_codes[3],
                    }
                    manifest = {"source_sha256": snapshot_digest(graph),
                                "allocations": {}}
                    for table in CRITICAL_TABLES:
                        cur.execute(
                            f'SELECT id,legal_entity_id FROM "ct_app"."{table}"'
                        )
                        from_db = dict(cur.fetchall())
                        manifest["allocations"][table] = [
                            {
                                "record_id": row["id"],
                                "company_code": synthetic_owner_codes[
                                    from_db[row["id"]]
                                ],
                                "evidence_ref": "FICTIONAL_CI_ONLY_SOURCE",
                            }
                            for row in graph[table]
                        ]
                    verified = evaluate_owner_mapping(graph, manifest)
                    self.assertEqual(verified["status"], "review_required")
                    self.assertFalse(verified["isolation_verified"])
                    self.assertTrue(verified["source_fingerprint_matches"])
                    # Missing mapping row must fail even though DB FKs pass.
                    plan_missing = {
                        "source_sha256": manifest["source_sha256"],
                        "allocations": {
                            table: list(rows)
                            for table, rows in manifest["allocations"].items()
                        },
                    }
                    plan_missing["allocations"]["cash_accounts"].pop()
                    self.assertEqual(
                        evaluate_owner_mapping(graph, plan_missing)["status"],
                        "blocked",
                    )
                    # A correct but stale plan must never pass after a row
                    # fingerprint changes.
                    changed_graph = {
                        table: [dict(row) for row in rows]
                        for table, rows in graph.items()
                    }
                    changed_graph["cash_accounts"][0]["row_hash"] = "a" * 32
                    self.assertIn(
                        "stale_or_invalid_source",
                        evaluate_owner_mapping(
                            changed_graph, manifest
                        )["issue_codes"],
                    )

                    # Even a string called "admin" is not privileged.
                    self.assertEqual(
                        read_company_records_on_cursor(
                            cur, "admin", group_codes[3], "Banka / Kasa"
                        ), ("forbidden", []),
                    )
                    # Explicitly revoke A inside the disposable transaction.
                    cur.execute(
                        'UPDATE "ct_app"."company_read_grants" SET can_read=FALSE '
                        'WHERE principal_id=%s AND legal_entity_id=%s',
                        ("ci-scoped-reader", ids["CI_A"]),
                    )
                    self.assertEqual(
                        read_company_records_on_cursor(
                            cur, "ci-scoped-reader", group_codes[0], "Banka / Kasa"
                        ), ("forbidden", []),
                    )

                raise IntentionallyRollback()
        except IntentionallyRollback:
            pass

        with self.conn.cursor() as cur:
            self.assertEqual(
                company_schema_status_on_cursor(cur),
                "legacy_schema_only",
            )
            cur.execute(
                "SELECT COUNT(*) FROM pg_class c JOIN pg_namespace n "
                "ON n.oid=c.relnamespace WHERE n.nspname='ct_app' "
                "AND c.relname='legal_entities'"
            )
            self.assertEqual(cur.fetchone()[0], 0)
            for table in ("company_read_grants", "company_write_grants",
                          "company_warehouse_scope", "company_operation_audit"):
                cur.execute(
                    "SELECT to_regclass(%s)", ("ct_app." + table,)
                )
                self.assertIsNone(cur.fetchone()[0])
            cur.execute(
                "SELECT COUNT(*) FROM information_schema.columns "
                "WHERE table_schema='ct_app' AND column_name='legal_entity_id'"
            )
            self.assertEqual(cur.fetchone()[0], 0)

    def test_actual_crm_purchase_stock_quality_and_finance(self):
        customer = create_customer(self.url, "SALES", "CI FICTIONAL CUSTOMER")
        self.assertEqual(customer[0], "ok", customer[0])
        self.assertEqual(
            create_customer(self.url, "ADMIN", "ci fictional customer")[0],
            "duplicate_customer",
        )
        product = create_product(
            self.url, "PURCHASING", "CI FAKE INGREDIENT", "CI FAKE SUPPLIER"
        )
        self.assertEqual(product[0], "ok", product[0])
        status, warehouse = create_warehouse(
            self.url, "PURCHASING", "CI FICTIONAL WAREHOUSE",
            city="London", actor="ci-purchaser",
        )
        self.assertEqual(status, "ok")
        self.assertEqual(
            create_warehouse(
                self.url, "PURCHASING", "CI FICTIONAL WAREHOUSE",
                actor="ci-purchaser",
            )[0],
            "duplicate_warehouse",
        )
        self.execute(
            'INSERT INTO "ct_app"."cash_accounts" (name,currency,balance) '
            'VALUES (%s,%s,%s)',
            ("CI FICTIONAL BANK", "EUR", Decimal("2000")),
        )
        bank = self.execute(
            'SELECT id FROM "ct_app"."cash_accounts" WHERE name=%s',
            ("CI FICTIONAL BANK",),
        )[0]
        po = create_purchase_order(
            self.url, "PURCHASING", "CI-PO-001", "CI FAKE SUPPLIER",
            product[1], warehouse, "1000", "2.25", "EUR"
        )
        self.assertEqual(po[0], "ok", po[0])
        self.assertEqual(
            create_purchase_order(
                self.url, "ADMIN", "CI-PO-001", "CI FAKE SUPPLIER",
                product[1], warehouse, 1000, 2.25, "EUR"
            )[0],
            "duplicate_po",
        )
        shipment = create_shipment(
            self.url, "PURCHASING", po[1], "CI-SHIP-001", 600
        )
        self.assertEqual(shipment[0], "ok", shipment[0])
        self.assertEqual(
            create_shipment(self.url, "PURCHASING", po[1], "CI-OVER", 500)[0],
            "over_shipment",
        )
        receipt = receive_shipment(self.url, "PURCHASING", shipment[1])
        self.assertEqual(receipt[0], "ok", receipt[0])
        self.assertEqual(
            receive_shipment(self.url, "PURCHASING", shipment[1])[0],
            "already_received_or_cancelled",
        )
        hold = hold_inventory_lot(
            self.url, "QUALITY", receipt[1], "CI-QA-001", 100,
            "Synthetic lot hold for isolated CI"
        )
        self.assertEqual(hold[0], "ok", hold[0])
        payable = create_payable(
            self.url, "FINANCE", "CI FAKE SUPPLIER", po[1],
            "CI-INV-001", "2026-12-01", 1350, "EUR"
        )
        self.assertEqual(payable[0], "ok", payable[0])
        self.assertEqual(
            pay_supplier(
                self.url, "FINANCE", payable[1], bank, 500,
                "CI-WIRE-001", "2026-10-10"
            )[0],
            "quality_hold_blocks_payment",
        )
        # Release must close its own quality case atomically.
        self.assertEqual(
            release_inventory_lot(
                self.url, "QUALITY", receipt[1], "CI fictional test resolved"
            )[0],
            "ok",
        )
        self.assertEqual(
            release_inventory_lot(
                self.url, "QUALITY", receipt[1], "Repeat release"
            )[0],
            "lot_not_on_hold",
        )
        self.assertEqual(
            self.execute(
                'SELECT status FROM "ct_app"."quality_cases" WHERE id=%s',
                (hold[1],),
            )[0],
            "Kapandı",
        )
        self.assertEqual(
            pay_supplier(
                self.url, "FINANCE", payable[1], bank, 500,
                "CI-WIRE-001", "2026-10-10"
            )[0],
            "ok",
        )
        self.assertEqual(
            pay_supplier(
                self.url, "FINANCE", payable[1], bank, 100,
                "CI-WIRE-001", "2026-10-10"
            )[0],
            "duplicate_payment",
        )
        # A bank reference must not be reused for another invoice.
        another = create_payable(
            self.url, "FINANCE", "CI FAKE SUPPLIER", po[1],
            "CI-INV-002", "2026-12-15", 100, "EUR"
        )
        self.assertEqual(another[0], "ok")
        self.assertEqual(
            pay_supplier(
                self.url, "FINANCE", another[1], bank, 100,
                "CI-WIRE-001", "2026-10-10"
            )[0],
            "duplicate_payment",
        )
        self.assertEqual(
            pay_supplier(
                self.url, "FINANCE", payable[1], bank, 850,
                "CI-WIRE-002", "2026-10-10"
            )[0],
            "ok",
        )
        self.assertEqual(
            self.execute('SELECT paid_amount FROM "ct_app"."payables" WHERE id=%s',
                         (payable[1],))[0],
            1350,
        )
        self.assertEqual(
            self.execute('SELECT balance FROM "ct_app"."cash_accounts" WHERE id=%s',
                         (bank,))[0],
            650,
        )
        status, counts = read_operational_counts(self.url)
        self.assertEqual(status, "ok", status)
        self.assertEqual(counts["customers"], 1)
        self.assertEqual(counts["inventory_lots"], 1)
        self.assertEqual(counts["quality_cases"], 1)
        self.assertEqual(counts["finance_transactions"], 2)
        actor_audits = self.execute(
            'SELECT COUNT(*) FROM "ct_app"."audit_log" '
            "WHERE username=%s AND action=%s",
            ("ci-purchaser", "create_warehouse"),
        )[0]
        self.assertEqual(actor_audits, 1)
        self.assertGreaterEqual(
            self.execute('SELECT COUNT(*) FROM "ct_app"."audit_log"')[0],
            10,
        )

        # PostgreSQL 360 reads real relational records, not SQLite snapshots.
        for section, wanted_key in (
            ("Müşteriler", "name"), ("Ürün Kataloğu", "supplier"),
            ("Satın Alma", "po_number"), ("Sevkiyat", "shipment_ref"),
            ("Stok", "quality_status"), ("Kalite", "case_no"),
            ("Borçlar", "invoice_no"), ("Banka / Kasa", "balance"),
            ("Finans Hareketleri", "reference"),
        ):
            with self.subTest(section=section):
                workspace_status, rows = read_operational_workspace(
                    self.url, section,
                )
                self.assertEqual(workspace_status, "ok")
                self.assertTrue(rows)
                self.assertIn(wanted_key, rows[0])



    def test_live_security_posture_is_read_only_and_never_certifies_supabase(self):
        """Security audit introspects disposable Docker PostgreSQL only."""
        from scripts.postgres_security_audit import audit_postgres_security

        before = self.execute(
            'SELECT COUNT(*) FROM "ct_app"."audit_log"'
        )[0]
        report = audit_postgres_security(self.url)
        self.assertEqual(report["status"], "review_required")
        self.assertEqual(len(report["checks"]), 5)
        self.assertEqual(len(report["external"]), 4)
        self.assertTrue(any(
            "Supabase" in item for item in report["external"]
        ))
        # PostgreSQL Docker test role may be elevated and TLS is disabled
        # ONLY because it uses the narrowly allowed localhost CI database.
        self.assertEqual(
            self.execute('SELECT COUNT(*) FROM "ct_app"."audit_log"')[0],
            before,
        )

    def test_master_csv_import_is_atomic_and_audited_on_disposable_postgres(self):
        """Real CI-only test of customer/product/warehouse import and rollback."""
        from scripts.postgres_master_import import (
            APPROVAL, import_new_masters, parse_master_csv, template_csv,
        )
        import csv
        from io import StringIO

        def csv_bytes(domain, names, **kwargs):
            fields = template_csv(domain).decode("utf-8-sig").strip().split(",")
            buf = StringIO(newline="")
            writer = csv.DictWriter(buf, fieldnames=fields)
            writer.writeheader()
            for name in names:
                writer.writerow({"name": name, **kwargs})
            return buf.getvalue().encode("utf-8")

        before_finance = self.execute(
            'SELECT COUNT(*) FROM "ct_app"."finance_transactions"'
        )[0]
        for domain, names, fields in (
            ("Müşteriler", ["CI BULK CUSTOMER 01", "CI BULK CUSTOMER 02"],
             {"country": "Türkiye", "sector": "Gıda"}),
            ("Ürünler", ["CI BULK PRODUCT 01", "CI BULK PRODUCT 02"],
             {"supplier": "CI FAKE MANUFACTURER", "category": "Ingredient"}),
            ("Depolar", ["CI BULK WAREHOUSE 01", "CI BULK WAREHOUSE 02"],
             {"warehouse_type": "Normal Depo", "city": "London"}),
        ):
            with self.subTest(domain=domain):
                status, rows = parse_master_csv(csv_bytes(domain, names, **fields), domain)
                self.assertEqual(status, "ok")
                result, n = import_new_masters(
                    self.url, role="ADMIN", actor="ci-admin-import",
                    domain=domain, rows=rows,
                    confirmation=APPROVAL, backup_confirmed=True,
                )
                self.assertEqual((result, n), ("ok", 2))
                for name in names:
                    table = {
                        "Müşteriler": "customers",
                        "Ürünler": "product_catalog",
                        "Depolar": "warehouses",
                    }[domain]
                    self.assertEqual(
                        self.execute(
                            f'SELECT COUNT(*) FROM "ct_app"."{table}" '
                            'WHERE name=%s', (name,),
                        )[0],
                        1,
                    )
                # Reimporting the exact same file must never insert records.
                self.assertEqual(
                    import_new_masters(
                        self.url, role="ADMIN", actor="ci-admin-import",
                        domain=domain, rows=rows,
                        confirmation=APPROVAL, backup_confirmed=True,
                    ),
                    ("duplicate_existing", 0),
                )

        # The second name already exists; first inserted row must roll back.
        bad_status, bad_rows = parse_master_csv(
            csv_bytes("Müşteriler", [
                "CI BULK ATOMIC ROLLBACK", "CI BULK CUSTOMER 01",
            ]), "Müşteriler",
        )
        self.assertEqual(bad_status, "ok")
        self.assertEqual(
            import_new_masters(
                self.url, role="ADMIN", actor="ci-admin-import",
                domain="Müşteriler", rows=bad_rows,
                confirmation=APPROVAL, backup_confirmed=True,
            ),
            ("duplicate_existing", 0),
        )
        self.assertEqual(
            self.execute(
                'SELECT COUNT(*) FROM "ct_app"."customers" WHERE name=%s',
                ("CI BULK ATOMIC ROLLBACK",),
            )[0], 0,
        )
        self.assertEqual(
            self.execute(
                'SELECT COUNT(*) FROM "ct_app"."audit_log" '
                "WHERE username='ci-admin-import' AND action='bulk_import_new'"
            )[0], 6,
        )
        self.assertEqual(
            self.execute('SELECT COUNT(*) FROM "ct_app"."finance_transactions"')[0],
            before_finance,
        )

    def test_legacy_sql_forms_read_and_write_ct_app_only(self):
        """Actual legacy business facade writes persist in disposable PostgreSQL."""
        from unittest.mock import patch
        import control_tower as ct
        import security_admin as auth
        from scripts.postgres_operational_write import verified_live_request
        fictional_user = {
            "username": "ci-legacy-admin", "role": "ADMIN",
            "display_name": "CI Legacy Admin",
        }
        with patch.dict(os.environ, {"DATABASE_URL": self.url}):
            with patch.object(auth, "current_user", return_value=fictional_user):
                with patch.object(ct, "current_user", return_value=fictional_user):
                    with patch.object(ct, "authorize_write", return_value=True):
                        with verified_live_request():
                            ct.execute(
                                "INSERT INTO customers (name, country, sector) "
                                "VALUES (?,?,?)",
                                ("CI LEGACY CUSTOMER", "Türkiye", "Food"),
                            )
                            got = ct.query_df(
                                "SELECT id,name,country FROM customers WHERE name=?",
                                ("CI LEGACY CUSTOMER",),
                            )
                            self.assertEqual(len(got), 1)
                            self.assertEqual(got.iloc[0]["country"], "Türkiye")
                            customer_id = int(got.iloc[0]["id"])
                            with ct.get_conn() as conn:
                                conn.execute(
                                    "UPDATE customers SET sector=? WHERE id=?",
                                    ("Ingredients", customer_id),
                                )
                                conn.commit()
                            self.assertEqual(
                                ct.query_df(
                                    "SELECT sector FROM customers WHERE id=?",
                                    (customer_id,),
                                ).iloc[0]["sector"],
                                "Ingredients",
                            )
        # New connections confirm durable persistence, unlike demo SQLite.
        self.assertEqual(
            self.execute(
                'SELECT sector FROM "ct_app"."customers" WHERE name=%s',
                ("CI LEGACY CUSTOMER",),
            )[0],
            "Ingredients",
        )
        self.assertEqual(
            self.execute(
                'SELECT COUNT(*) FROM "ct_app"."audit_log" '
                "WHERE username=%s AND table_name='customers'",
                ("ci-legacy-admin",),
            )[0],
            2,
        )

    def test_control_tower_postgres_live_streamlit_smoke(self):
        """Real 26-table PostgreSQL backend exercised through all Streamlit tabs."""
        import tempfile
        from pathlib import Path
        from unittest.mock import patch
        from streamlit.testing.v1 import AppTest
        import control_tower as ct
        import security_admin as auth

        def fake_secret(name, default=""):
            return "ci-only-password" if name == "CONTROL_TOWER_PASSWORD" else default

        with tempfile.TemporaryDirectory() as tmp:
            with patch.dict(os.environ, {"DATABASE_URL": self.url}):
                with patch.object(ct, "DB_PATH", Path(tmp) / "sqlite-never-created.db"):
                    with patch.object(auth, "_secret", side_effect=fake_secret):
                        app = AppTest.from_file(
                            str(Path(__file__).resolve().parents[1] / "app.py"),
                            default_timeout=110,
                        )
                        app.session_state["ct_user"] = {
                            "username": "ci-admin",
                            "display_name": "CI Admin",
                            "role": "ADMIN",
                        }
                        app.session_state["ct_session_id"] = "ci-session"
                        app.run()
                        self.assertFalse(
                            app.exception, str(app.exception),
                        )
                        # The cutover must not open a new SQLite file.
                        self.assertFalse(ct.DB_PATH.exists())
                        self.assertTrue(
                            any("PostgreSQL" in t.label for t in app.tabs)
                        )
                        # Backup entry must be reachable on a phone without
                        # opening the nested System tab.
                        self.assertTrue(
                            any(
                                "PostgreSQL yedekleme" in e.label
                                for e in app.get("expander")
                            ),
                            "Mobile quick-access PostgreSQL backup is missing.",
                        )
                        self.assertTrue(
                            any(
                                "Grup Şirketleri" in e.label
                                for e in app.get("expander")
                            ),
                            "Mobile four-company readiness panel is missing.",
                        )


    def test_encrypted_backup_roundtrip_on_disposable_postgres(self):
        """Encrypt an actual PostgreSQL export, validate and decrypt in memory."""
        from scripts.postgres_backup import export_postgres_backup
        from scripts.postgres_encrypted_backup import (
            decrypt_export_zip, encrypt_export_zip, inspect_encrypted_export,
        )
        passphrase = "Only-a-fictional-CI-password-2026!"
        status, archive = export_postgres_backup(self.url)
        self.assertEqual(status, "ok")
        result, cipher = encrypt_export_zip(archive, passphrase)
        self.assertEqual(result, "encrypted")
        self.assertNotEqual(cipher, archive)
        self.assertNotIn(archive, cipher)
        verified, summary = inspect_encrypted_export(cipher, passphrase)
        self.assertEqual(verified, "verified_encrypted")
        self.assertEqual(summary["table_count"], 26)
        self.assertFalse(summary["restoration_tested"])
        decrypt_status, restored_zip = decrypt_export_zip(cipher, passphrase)
        self.assertEqual(decrypt_status, "decrypted")
        self.assertEqual(restored_zip, archive)

    def test_security_role_access_audit_on_disposable_postgres(self):
        """Read-only pg_catalog security metadata, including absent API roles."""
        from scripts.postgres_security_audit import audit_postgres_security
        result = audit_postgres_security(self.url)
        self.assertEqual(result["status"], "review_required")
        self.assertEqual(len(result["checks"]), 5)
        api = next(
            x for x in result["checks"] if "API rolleri" in x["label"]
        )
        self.assertEqual(api["status"], "uygun")
        self.assertEqual(len(result["external"]), 4)

    def test_postgres_live_backup_has_26_tables_and_hash_manifest(self):
        """Export a consistent, real, read-only backup of fictional Docker data."""
        import io
        import json
        import zipfile
        import hashlib
        from scripts.postgres_backup import export_postgres_backup

        status, archive = export_postgres_backup(self.url)
        self.assertEqual(status, "ok")
        self.assertIsInstance(archive, bytes)
        # Exercise the same verification that an ADMIN runs from their phone.
        from scripts.postgres_backup_verify import inspect_export_zip
        verified_status, verification = inspect_export_zip(archive)
        self.assertEqual(verified_status, "verified_format")
        self.assertEqual(verification["table_count"], 26)
        self.assertGreaterEqual(verification["row_count"], 1)
        self.assertFalse(verification["restoration_tested"])
        with zipfile.ZipFile(io.BytesIO(archive)) as z:
            manifest = json.loads(z.read("manifest.json"))
            self.assertEqual(manifest["schema"], "ct_app")
            self.assertEqual(len(manifest["tables"]), 26)
            for table, item in manifest["tables"].items():
                contents = z.read("tables/" + table + ".json")
                self.assertEqual(hashlib.sha256(contents).hexdigest(), item["sha256"])
                self.assertEqual(len(json.loads(contents)), item["row_count"])
            self.assertGreaterEqual(manifest["tables"]["customers"]["row_count"], 1)


    def test_postgres_zip_restore_drill_is_complete_and_rolled_back(self):
        """Roundtrip a real ct_app export into a transaction-only CI clone."""
        from scripts.postgres_backup import export_postgres_backup
        from scripts.postgres_restore_drill import verify_disposable_backup_restore

        before = self.execute('SELECT COUNT(*) FROM "ct_app"."customers"')[0]
        status, payload = export_postgres_backup(self.url)
        self.assertEqual(status, "ok", status)

        result, report = verify_disposable_backup_restore(self.url, payload)
        self.assertEqual(result, "verified", result)
        self.assertEqual(report["tables"], 26)
        self.assertTrue(report["rolled_back"])
        self.assertGreaterEqual(report["rows"], 1)

        # A schema created solely inside the trial transaction must vanish.
        self.assertFalse(self.execute(
            "SELECT EXISTS(SELECT 1 FROM pg_namespace WHERE nspname=%s)",
            ("ct_restore_verify",),
        )[0])
        # The original ci ct_app schema is untouched.
        self.assertEqual(
            self.execute('SELECT COUNT(*) FROM "ct_app"."customers"')[0],
            before,
        )

    def test_all_role_portals_use_live_postgres_without_sqlite(self):
        """Verify non-admin role pages in the disposable PG live backend."""
        import tempfile
        from pathlib import Path
        from unittest.mock import patch
        from streamlit.testing.v1 import AppTest
        import control_tower as ct
        import security_admin as auth

        def fake_secret(name, default=""):
            return "ci-only-password" if name == "CONTROL_TOWER_PASSWORD" else default

        with tempfile.TemporaryDirectory() as tmp:
            with patch.dict(os.environ, {"DATABASE_URL": self.url}):
                with patch.object(ct, "DB_PATH", Path(tmp) / "no-sqlite.db"):
                    with patch.object(auth, "_secret", side_effect=fake_secret):
                        for role in ("SALES", "PURCHASING", "QUALITY", "FINANCE", "VIEWER"):
                            with self.subTest(role=role):
                                app = AppTest.from_file(
                                    str(Path(__file__).resolve().parents[1] / "app.py"),
                                    default_timeout=110,
                                )
                                app.session_state["ct_user"] = {
                                    "username": "ci-" + role.lower(),
                                    "display_name": "CI " + role,
                                    "role": role,
                                }
                                app.session_state["ct_session_id"] = "ci-session-" + role
                                app.run()
                                self.assertFalse(app.exception, str(app.exception))
                        self.assertFalse(ct.DB_PATH.exists())


    def test_operational_reconciliation_reads_actual_disposable_pg(self):
        """Detect a fictional stock anomaly and verify no data is repaired."""
        from scripts.postgres_reconciliation import check_operational_consistency

        healthy = check_operational_consistency(self.url)
        self.assertIn(healthy["status"], ("ok", "issues_found"))
        self.assertEqual(len(healthy["checks"]), 10)
        self.assertTrue(all(
            isinstance(check["count"], int)
            for check in healthy["checks"]
        ))
        with self.conn.cursor() as cur:
            cur.execute(
                'INSERT INTO "ct_app"."warehouses" (name) VALUES (%s) RETURNING id',
                ("CI RECON ONLY WAREHOUSE",),
            )
            warehouse = int(cur.fetchone()[0])
            cur.execute(
                'INSERT INTO "ct_app"."inventory_lots" '
                '(product_name,warehouse_id,quantity_received_kg,'
                'quantity_available_kg,quantity_reserved_kg,quality_hold_kg) '
                'VALUES (%s,%s,%s,%s,%s,%s) RETURNING id',
                ("CI FICTIONAL NEGATIVE STOCK", warehouse, 20, 20, 60, 0),
            )
            stock_id = int(cur.fetchone()[0])
        try:
            anomalous = check_operational_consistency(self.url)
            self.assertEqual(anomalous["status"], "issues_found")
            invalid = next(
                item for item in anomalous["checks"]
                if item["id"] == "invalid_stock_quantities"
            )
            self.assertGreaterEqual(invalid["count"], 1)
            # Read-only audit must never repair the bogus stock reservation.
            reserved = self.execute(
                'SELECT quantity_reserved_kg FROM "ct_app"."inventory_lots" '
                'WHERE id=%s', (stock_id,),
            )[0]
            self.assertEqual(float(reserved), 60.0)
        finally:
            with self.conn.cursor() as cur:
                cur.execute(
                    'DELETE FROM "ct_app"."inventory_lots" WHERE id=%s',
                    (stock_id,),
                )
                cur.execute(
                    'DELETE FROM "ct_app"."warehouses" WHERE id=%s',
                    (warehouse,),
                )
        healthy_again = check_operational_consistency(self.url)
        self.assertEqual(healthy_again["status"], healthy["status"])
        self.assertEqual(healthy_again["checks"], healthy["checks"])


if __name__ == "__main__":
    unittest.main()
