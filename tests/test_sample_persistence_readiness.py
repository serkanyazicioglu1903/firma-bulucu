import unittest
from scripts.sample_persistence_readiness import sample_persistence_readiness_on_cursor

class Cursor:
    def __init__(self, rows): self.rows=rows; self.sql=""
    def execute(self, sql): self.sql=sql
    def fetchall(self): return self.rows

class SamplePersistenceReadinessTests(unittest.TestCase):
    def test_missing_production_tables_block(self):
        c=Cursor([('ct_demo','companies',True,True)])
        r=sample_persistence_readiness_on_cursor(c)
        self.assertFalse(r['ready'])
        self.assertIn('sample_shipments',r['missing'])
        self.assertTrue(r['demo_is_not_production'])

    def test_rls_must_be_forced(self):
        names=('legal_entities','company_login_bindings','company_read_grants',
               'company_write_grants','sample_shipments')
        c=Cursor([('ct_app',n,True,False) for n in names])
        r=sample_persistence_readiness_on_cursor(c)
        self.assertFalse(r['ready'])
        self.assertEqual(len(r['rls_not_forced']),5)

    def test_required_security_metadata_passes(self):
        names=('legal_entities','company_login_bindings','company_read_grants',
               'company_write_grants','sample_shipments')
        c=Cursor([('ct_app',n,True,True) for n in names])
        self.assertTrue(sample_persistence_readiness_on_cursor(c)['ready'])

if __name__=='__main__': unittest.main()
