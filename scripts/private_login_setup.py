"""Prepare login settings locally; never connect, activate runtime, or print secrets.

Run from a private directory outside the checkout:
python /path/to/firma-bulucu/scripts/private_login_setup.py
Copy the two generated settings into Streamlit Secrets, preserving other settings.
This does not provision DB roles or replace migration/restore verification.
"""
import getpass
import hashlib
import json
import os
from pathlib import Path
import secrets


def login_settings(password, confirmation):
    if len(password) < 14 or password != confirmation:
        raise ValueError('Parolalar aynı ve en az 14 karakter olmalı.')
    salt = secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac('sha256', password.encode(), salt.encode(), 200_000).hex()
    users = {'users': [{'username': 'serkan', 'display_name': 'Serkan',
                        'role': 'ADMIN', 'enabled': True,
                        'password_hash': f'pbkdf2_sha256$200000${salt}${digest}'}]}
    # JSON quoted strings are valid TOML basic strings. No plaintext password.
    return ('APP_USERS_JSON = ' + json.dumps(json.dumps(users)) + '\n'
            'CT_COMPANY_SESSION_SIGNING_KEY = ' + json.dumps(secrets.token_hex(32)) + '\n')


def save_settings(destination, content):
    path = Path(destination).absolute()
    checkout = Path(__file__).resolve().parent.parent
    if path.resolve().is_relative_to(checkout):
        raise ValueError('Ayar dosyası kod deposunun dışında saklanmalı.')
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, 'w', encoding='utf-8') as output:
        output.write(content)
        output.flush()
        os.fsync(output.fileno())


def main():
    if not os.isatty(0):
        print('Gizli parola girişi için Terminal içinde çalıştırın.')
        return 1
    try:
        password = getpass.getpass('Yeni uygulama parolası (en az 14 karakter): ')
        confirmation = getpass.getpass('Parolayı tekrar girin: ')
        content = login_settings(password, confirmation)
        save_settings('as-control-tower-login.private.toml', content)
    except (OSError, ValueError, EOFError):
        print('Dosya oluşturulamadı. Parolaları, konumu ve dosyanın zaten var olmadığını kontrol edin.')
        return 1
    print('Özel ayar dosyası oluşturuldu. Mevcut Streamlit ayarlarını silmeden iki ayarı ekleyin.')
    print('Dosyayı veya içeriğini sohbete/GitHub’a yüklemeyin. Veritabanı geçişi henüz yapılmadı.')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
