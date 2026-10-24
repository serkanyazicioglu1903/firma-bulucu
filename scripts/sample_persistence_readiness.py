"""Fail-closed, read-only readiness check for production sample persistence.

The existing ct_app database is not a tenant-scoped runtime. Never use
the legacy admin DATABASE_URL to persist samples.
"""
def sample_persistence_readiness_on_cursor(cur):
    cur.execute("""
        SELECT n.nspname, c.relname, c.relrowsecurity, c.relforcerowsecurity
        FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace
        WHERE c.relkind='r'
          AND ((n.nspname='ct_app' AND c.relname IN
                 ('legal_entities','company_login_bindings','company_read_grants',
                  'company_write_grants','sample_shipments'))
               OR (n.nspname='ct_demo' AND c.relname='companies'))
    """)
    rows = {(schema, name): (bool(rls), bool(force)) for schema,name,rls,force in cur.fetchall()}
    required = ('legal_entities','company_login_bindings','company_read_grants',
                'company_write_grants','sample_shipments')
    missing = [name for name in required if ('ct_app', name) not in rows]
    insecure = [name for name in required if ('ct_app',name) in rows
                and rows[('ct_app',name)] != (True, True)]
    return {
        'ready': not missing and not insecure,
        'missing': missing,
        'rls_not_forced': insecure,
        'demo_is_not_production': ('ct_demo','companies') in rows,
    }
