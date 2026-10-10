"""Start an isolated local evaluation. Never opens the normal application DB."""
import argparse
import getpass
import os
from pathlib import Path
import subprocess
import sys
import tempfile


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--demo', action='store_true', help='Load explicitly fictional sample records')
    parser.add_argument('--lan', action='store_true', help='Allow a phone on the same trusted Wi-Fi to connect')
    args = parser.parse_args()
    password = getpass.getpass('Önizleme şifresi (en az 12 karakter): ')
    if len(password) < 12:
        parser.error('En az 12 karakter kullanın.')
    with tempfile.TemporaryDirectory(prefix='as-control-tower-preview-') as folder:
        env = os.environ.copy()
        env.update(AS_CONTROL_TOWER_BACKEND='sqlite', AS_CONTROL_TOWER_DB=str(Path(folder)/'preview.db'),
                   AS_CONTROL_TOWER_DEMO_SEED='1' if args.demo else '0',
                   CONTROL_TOWER_PASSWORD=password, APP_USERS_JSON='')
        print('Kullanıcı: serkan. Geçici önizleme; kapatınca örnek kayıtlar silinir.')
        subprocess.run([sys.executable,'-m','streamlit','run',str(Path(__file__).with_name('app.py')),
                        '--server.address','0.0.0.0' if args.lan else '127.0.0.1',
                        '--server.headless','true','--browser.gatherUsageStats','false'],env=env,check=True)


if __name__ == '__main__':
    main()
