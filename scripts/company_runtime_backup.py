"""Encrypted native PostgreSQL schema/data backup including runtime registries.

No startup/scheduled side effects. Caller explicitly supplies a dedicated
backup connection, never an app-user connection. pg_dump fails rather than
silently exporting partial RLS-filtered data. Does not back up cluster login
passwords, Supabase Auth/Storage or replace provider PITR.
"""
import os
import subprocess
from urllib.parse import urlsplit, unquote

from scripts.postgres_encrypted_backup import _acceptable_password, _derive_key
from scripts.postgres_connection import sslmode_for

MAGIC = b'ASCTPG01'
MAX_BYTES = 128 * 1024 * 1024


def connection_environment(url):
    p = urlsplit(url)
    if (p.scheme not in ('postgresql','postgres') or not p.hostname
            or not p.username or not p.password or not p.path.strip('/')
            or p.query or p.fragment):
        raise ValueError('invalid_url')
    # Never place credentials in process arguments or inherit external PGOPTIONS.
    env = {k:v for k,v in os.environ.items() if not k.startswith('PG')}
    env.update(PGHOST=p.hostname, PGPORT=str(p.port or 5432),
               PGUSER=unquote(p.username), PGPASSWORD=unquote(p.password),
               PGDATABASE=unquote(p.path[1:]), PGSSLMODE=sslmode_for(url),
               PGCONNECT_TIMEOUT='8')
    return env


def encrypt_dump(dump, passphrase):
    if not _acceptable_password(passphrase):
        return 'weak_passphrase', None
    if not isinstance(dump,bytes) or not dump.startswith(b'PGDMP') or len(dump)>MAX_BYTES:
        return 'invalid_dump', None
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    salt, nonce = os.urandom(16), os.urandom(12)
    aad = MAGIC+salt
    return 'encrypted', aad+nonce+AESGCM(_derive_key(passphrase,salt)).encrypt(nonce,dump,aad)


def decrypt_dump(encrypted, passphrase):
    if (not isinstance(encrypted,bytes) or not encrypted.startswith(MAGIC)
            or not 52<len(encrypted)<=MAX_BYTES+52 or not _acceptable_password(passphrase)):
        return 'invalid_backup', None
    try:
        from cryptography.hazmat.primitives.ciphers.aead import AESGCM
        salt,nonce=encrypted[8:24],encrypted[24:36]
        dump=AESGCM(_derive_key(passphrase,salt)).decrypt(nonce,encrypted[36:],encrypted[:24])
        if not dump.startswith(b'PGDMP'):
            return 'invalid_backup',None
        return 'decrypted',dump
    except Exception:
        return 'wrong_password_or_corrupt',None


def backup_runtime(url, passphrase):
    """Read-only pg_dump; return ciphertext only, never stderr or plaintext."""
    if not _acceptable_password(passphrase):
        return 'weak_passphrase',None
    try:
        env=connection_environment(url)
        env['PGOPTIONS']='-c default_transaction_read_only=on -c statement_timeout=120000'
        result=subprocess.run(['pg_dump','--format=custom','--schema=ct_app','--no-password',
                               '--lock-wait-timeout=5000'],env=env,capture_output=True,timeout=150)
        if result.returncode or result.stderr:
            return 'dump_failed',None
        return encrypt_dump(result.stdout,passphrase)
    except Exception:
        return 'backup_failed',None


def restore_disposable(encrypted,passphrase,url):
    """Restore ONLY into an empty, fixed-name local CI database. No live restore."""
    try:
        p=urlsplit(url)
        if (os.environ.get('CT_LOCAL_POSTGRES_TEST')!='1'
                or p.hostname not in ('127.0.0.1','localhost') or p.port!=5432
                or p.username!='ct_ci' or p.path!='/ct_ci_control_tower_restore'
                or p.query or p.fragment):
            return 'disposable_target_required'
        status,dump=decrypt_dump(encrypted,passphrase)
        if status!='decrypted':
            return status
        import psycopg
        with psycopg.connect(url,sslmode='disable',autocommit=True) as conn,conn.cursor() as cur:
            cur.execute("SELECT to_regnamespace('ct_app')")
            if cur.fetchone()[0] is not None:
                return 'target_not_empty'
        env=connection_environment(url)
        env['PGSSLMODE']='disable'
        # No --clean, --create, production URL, role password, or persistent dump file.
        result=subprocess.run(['pg_restore','--dbname=ct_ci_control_tower_restore','--no-owner',
                               '--single-transaction','--exit-on-error','--no-password'],
                              env=env,input=dump,capture_output=True,timeout=150)
        return 'restored' if result.returncode==0 else 'restore_failed'
    except Exception:
        return 'restore_failed'


def main():
    import argparse
    parser=argparse.ArgumentParser(description='Explicit read-only encrypted ct_app backup')
    parser.add_argument('--output',required=True,help='New encrypted .asctpg file; existing files are never overwritten')
    args=parser.parse_args()
    status,encrypted=backup_runtime(os.environ.get('CT_RUNTIME_BACKUP_DATABASE_URL',''),os.environ.get('CT_RUNTIME_BACKUP_PASSPHRASE',''))
    if status!='encrypted':
        print(status)
        return 1
    try:
        fd=os.open(args.output,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
        with os.fdopen(fd,'wb') as out:
            out.write(encrypted)
            out.flush()
            os.fsync(out.fileno())
    except OSError:
        print('output_unavailable')
        return 1
    print('encrypted_backup_saved')
    return 0


if __name__=='__main__':
    raise SystemExit(main())
