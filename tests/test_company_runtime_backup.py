from unittest.mock import patch
from scripts.company_runtime_backup import encrypt_dump,decrypt_dump,restore_disposable,connection_environment,backup_runtime

PASS='synthetic-backup-passphrase-2026'

def test_authenticated_encryption_roundtrip_and_tamper():
    source=b'PGDMP'+b'synthetic-test-only'*100
    status,encrypted=encrypt_dump(source,PASS)
    assert status=='encrypted'
    assert decrypt_dump(encrypted,PASS)==('decrypted',source)
    assert decrypt_dump(encrypted[:-1]+bytes([encrypted[-1]^1]),PASS)[1] is None
    assert decrypt_dump(encrypted,'different-strong-passphrase')[1] is None


def test_restore_rejects_external_database_without_connecting():
    with patch('psycopg.connect') as conn:
        assert restore_disposable(b'',PASS,'postgresql://fake:fake@example.com/db')=='disposable_target_required'
        conn.assert_not_called()


def test_process_arguments_never_contain_credentials():
    with patch('subprocess.run') as run:
        run.return_value.returncode=1
        assert backup_runtime('postgresql://backup:fake-private-value@example.com/db',PASS)==('dump_failed',None)
        assert 'fake-private-value' not in str(run.call_args.args)
        assert run.call_args.kwargs['env']['PGPASSWORD']=='fake-private-value'
