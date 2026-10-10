"""Generate an additive, reviewable ct_staging migration. Never connects to a DB."""
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from scripts.build_pg_schema import sqlite_schema,create_table_sql,foreign_key_sql


def generate_migration():
    statements=['BEGIN;', 'SET LOCAL search_path TO ct_staging;',
        'ALTER TABLE receivables ADD COLUMN IF NOT EXISTS credit_amount DOUBLE PRECISION DEFAULT 0;']
    with sqlite_schema() as conn:
        tables=[r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND (name LIKE 'workflow_%' OR name='finance_reversals')")]
        for table in tables:
            statements.append(create_table_sql(conn,table).replace('CREATE TABLE ','CREATE TABLE IF NOT EXISTS ',1))
        for table in tables:
            for sql in foreign_key_sql(conn,table):
                name=sql.split('ADD CONSTRAINT "',1)[1].split('"',1)[0]
                statements.append("DO $$ BEGIN IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname='"+name+"' AND conrelid='ct_staging."+table+"'::regclass) THEN "+sql+" END IF; END $$;")
    statements.append('''CREATE OR REPLACE FUNCTION protect_workflow_quote() RETURNS trigger
        LANGUAGE plpgsql SET search_path FROM CURRENT AS $$
        BEGIN
            IF EXISTS (SELECT 1 FROM workflow_orders WHERE quote_id=OLD.id) THEN
                RAISE EXCEPTION 'Quote is locked by an integrated order';
            END IF;
            IF TG_OP='DELETE' THEN RETURN OLD; END IF;
            RETURN NEW;
        END; $$;
        DO $$ BEGIN
            IF NOT EXISTS (SELECT 1 FROM pg_trigger WHERE tgname='workflow_quote_frozen'
                AND tgrelid='ct_staging.quotes'::regclass) THEN
                CREATE TRIGGER workflow_quote_frozen BEFORE UPDATE OR DELETE ON quotes
                FOR EACH ROW EXECUTE FUNCTION protect_workflow_quote();
            END IF;
        END $$;''')
    statements.append('COMMIT;')
    return '\n\n'.join(statements)+'\n'


if __name__=='__main__':
    print(generate_migration())
