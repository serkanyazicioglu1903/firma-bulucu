"""Reviewable company-runtime DDL. Returns SQL only; never opens a connection.

Apply after foundation_ddl and explicit ownership backfill, in one approved
maintenance transaction. NULL owners cause failure, not automatic assignment.
Application roles are provisioned separately and receive no schema ownership.
"""
from scripts.build_pg_schema import sqlite_schema, quote
from scripts.four_company_foundation_ddl import private_company_tables


def runtime_ddl():
    tables = private_company_tables()
    statements = [
        'CREATE TABLE ct_app.company_login_bindings (principal_id TEXT PRIMARY KEY, db_role NAME UNIQUE NOT NULL, app_role TEXT NOT NULL CHECK (app_role IN (\'ADMIN\',\'VIEWER\')), enabled BOOLEAN NOT NULL DEFAULT FALSE)',
        'CREATE TABLE ct_app.company_requests (id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY, principal_id TEXT NOT NULL, legal_entity_id BIGINT NOT NULL REFERENCES ct_app.legal_entities(id), request_id UUID NOT NULL, operation TEXT NOT NULL, payload_hash TEXT NOT NULL, record_id BIGINT NOT NULL, UNIQUE(principal_id,request_id))',
    ]
    # Every parent reference between private tables carries company ownership.
    with sqlite_schema() as schema:
        for table in tables:
            target = 'ct_app.' + quote(table)
            statements += [f'ALTER TABLE {target} ALTER COLUMN legal_entity_id SET NOT NULL',
                           f'ALTER TABLE {target} ADD UNIQUE (id,legal_entity_id)']
        for table in tables:
            for fk in schema.execute('PRAGMA foreign_key_list(' + quote(table) + ')'):
                if fk[2] in tables:
                    statements.append(
                        f'ALTER TABLE ct_app.{quote(table)} ADD CONSTRAINT '
                        f'{quote("tenant_fk_" + table + "_" + str(fk[0]))} '
                        f'FOREIGN KEY ({quote(fk[3])},legal_entity_id) '
                        f'REFERENCES ct_app.{quote(fk[2])} ({quote(fk[4])},legal_entity_id)')
    # quality_case_id was added after initial table creation.
    statements.append('ALTER TABLE ct_app.inventory_lots ADD CONSTRAINT tenant_lot_case_fk FOREIGN KEY (quality_case_id,legal_entity_id) REFERENCES ct_app.quality_cases(id,legal_entity_id)')
    statements.append('ALTER TABLE ct_app.company_warehouse_scope ADD CONSTRAINT tenant_warehouse_fk FOREIGN KEY (warehouse_id,legal_entity_id) REFERENCES ct_app.warehouses(id,legal_entity_id)')
    binding = "EXISTS (SELECT 1 FROM ct_app.company_login_bindings b WHERE b.db_role=current_user AND b.enabled AND b.principal_id={principal})"
    for table in ('company_login_bindings', 'company_read_grants', 'company_write_grants',
                  'legal_entities', 'company_warehouse_scope', 'company_operation_audit',
                  'company_requests', 'product_catalog', 'audit_log', 'system_settings', *tables):
        target = 'ct_app.' + quote(table)
        statements += [f'ALTER TABLE {target} ENABLE ROW LEVEL SECURITY',
                       f'ALTER TABLE {target} FORCE ROW LEVEL SECURITY',
                       f'REVOKE ALL ON {target} FROM PUBLIC']
    statements.append('CREATE POLICY runtime_binding_read ON ct_app.company_login_bindings FOR SELECT USING (db_role=current_user AND enabled)')
    for table in ('company_read_grants', 'company_write_grants'):
        statements.append(f'CREATE POLICY runtime_grant_read ON ct_app.{table} FOR SELECT USING (' + binding.format(principal=table+'.principal_id') + ')')
    read = "EXISTS (SELECT 1 FROM ct_app.company_read_grants r JOIN ct_app.company_login_bindings b USING (principal_id) JOIN ct_app.legal_entities e ON e.id=r.legal_entity_id WHERE b.db_role=current_user AND b.enabled AND r.can_read AND e.active AND r.legal_entity_id={owner})"
    # legal_entities policy cannot recurse through itself.
    statements.append('CREATE POLICY runtime_entity_read ON ct_app.legal_entities FOR SELECT USING (active AND EXISTS (SELECT 1 FROM ct_app.company_read_grants r JOIN ct_app.company_login_bindings b USING (principal_id) WHERE b.db_role=current_user AND b.enabled AND r.can_read AND r.legal_entity_id=legal_entities.id))')
    write = "(" + read + ") AND EXISTS (SELECT 1 FROM ct_app.company_write_grants w JOIN ct_app.company_login_bindings b USING (principal_id) WHERE b.db_role=current_user AND b.enabled AND b.app_role='ADMIN' AND w.can_write AND w.legal_entity_id={owner})"
    for table in (*tables, 'company_warehouse_scope', 'company_operation_audit', 'company_requests'):
        target = 'ct_app.' + quote(table)
        owner = quote(table)+'.legal_entity_id'
        rp, wp = read.format(owner=owner), write.format(owner=owner)
        if table in ('company_operation_audit', 'company_requests'):
            wp += ' AND ' + binding.format(principal=quote(table)+'.principal_id')
        statements += [f'CREATE POLICY runtime_read ON {target} FOR SELECT USING ({rp})',
                       f'CREATE POLICY runtime_insert ON {target} FOR INSERT WITH CHECK ({wp})']
        if table in tables:
            statements.append(f'CREATE POLICY runtime_update ON {target} FOR UPDATE USING ({wp}) WITH CHECK ({wp})')
            # Even a user with grants to both companies cannot transfer a row.
            statements.append(f'CREATE TRIGGER immutable_company BEFORE UPDATE OF legal_entity_id ON {target} FOR EACH ROW EXECUTE FUNCTION ct_app.reject_company_transfer()')
    # Function is invoker-only and does not query business data.
    function = "CREATE FUNCTION ct_app.reject_company_transfer() RETURNS trigger LANGUAGE plpgsql SECURITY INVOKER SET search_path=pg_catalog AS $$ BEGIN IF NEW.legal_entity_id IS DISTINCT FROM OLD.legal_entity_id THEN RAISE EXCEPTION 'company_transfer_forbidden'; END IF; RETURN NEW; END $$"
    statements.insert(2, function)
    known = "EXISTS (SELECT 1 FROM ct_app.company_login_bindings b WHERE b.db_role=current_user AND b.enabled)"
    admin = "EXISTS (SELECT 1 FROM ct_app.company_login_bindings b WHERE b.db_role=current_user AND b.enabled AND b.app_role='ADMIN')"
    statements += [f'CREATE POLICY runtime_product_read ON ct_app.product_catalog FOR SELECT USING ({known})',
                   f'CREATE POLICY runtime_product_insert ON ct_app.product_catalog FOR INSERT WITH CHECK ({admin})']
    return tuple(statements)


def runtime_role_grants(role):
    """SQL for a separately created non-owner LOGIN role. No passwords or users."""
    from scripts.company_db_role_preflight import _ROLE, _DENIED_ROLES
    if not isinstance(role, str) or not _ROLE.fullmatch(role) or role in _DENIED_ROLES:
        raise ValueError('invalid_role')
    target = quote(role)
    registry = ('company_login_bindings','company_read_grants','company_write_grants','legal_entities')
    result = [f'GRANT USAGE ON SCHEMA ct_app TO {target}']
    result += [f'GRANT SELECT ON ct_app.{quote(t)} TO {target}' for t in registry]
    result += [f'GRANT SELECT,INSERT,UPDATE ON ct_app.{quote(t)} TO {target}' for t in private_company_tables()]
    result += [f'GRANT SELECT,INSERT ON ct_app.{quote(t)} TO {target}' for t in ('company_requests','company_operation_audit','company_warehouse_scope','product_catalog')]
    result += [f'GRANT USAGE ON ALL SEQUENCES IN SCHEMA ct_app TO {target}']
    return tuple(result)
