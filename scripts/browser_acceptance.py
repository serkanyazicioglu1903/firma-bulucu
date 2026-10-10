"""Isolated Chromium desktop/mobile-viewport acceptance; no deployment or live data."""
import os
import argparse
from pathlib import Path
import secrets
import subprocess
import sys
import tempfile
import time
import urllib.request
from playwright.sync_api import sync_playwright, expect

ROOT=Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--postgres-test', action='store_true')
    args = parser.parse_args()
    backend = {'AS_CONTROL_TOWER_BACKEND': 'sqlite'}
    if args.postgres_test:
        sys.path.insert(0, str(ROOT))
        import psycopg
        from scripts.postgres_workflow import validate_test_url
        from scripts.build_pg_schema import generate
        url = validate_test_url(os.environ.get('AS_CT_TEST_POSTGRES_URL', ''))
        with psycopg.connect(url, autocommit=True) as conn:
            conn.execute('DROP SCHEMA IF EXISTS ct_staging CASCADE')
            conn.execute(generate()[0])
        backend = {'AS_CONTROL_TOWER_BACKEND': 'postgres',
                   'AS_CONTROL_TOWER_POSTGRES_URL': url,
                   'AS_CONTROL_TOWER_POSTGRES_SCHEMA': 'ct_staging'}
    output=ROOT/('browser-artifacts-postgres' if args.postgres_test else 'browser-artifacts')
    output.mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='ct-browser-') as tmp:
        password=secrets.token_urlsafe(24)
        env=dict(os.environ,AS_CONTROL_TOWER_DB=str(Path(tmp)/'test.db'),
                 AS_CONTROL_TOWER_DEMO_SEED='1',CONTROL_TOWER_PASSWORD=password,APP_USERS_JSON='')
        env.update(backend)
        with (output/'server.log').open('w') as log:
            server=subprocess.Popen([sys.executable,'-m','streamlit','run',str(ROOT/'app.py'),
                '--server.address=127.0.0.1','--server.port=8503','--server.headless=true',
                '--browser.gatherUsageStats=false'],cwd=ROOT,env=env,stdout=log,stderr=log)
            try:
                for attempt in range(40):
                    try:
                        urllib.request.urlopen('http://127.0.0.1:8503/_stcore/health',timeout=1).close()
                        break
                    except OSError:
                        time.sleep(.25)
                else:
                    raise RuntimeError('Server did not become healthy')
                with sync_playwright() as p:
                    for engine in ('chromium','webkit'):
                        browser=getattr(p,engine).launch()
                        for name,width,height in [('desktop',1440,900),('phone',390,844)]:
                            context=browser.new_context(viewport={'width':width,'height':height},has_touch=name=='phone',is_mobile=name=='phone')
                            page=context.new_page()
                            page.set_default_timeout(30000)
                            page.goto('http://127.0.0.1:8503')
                            expect(page.get_by_label('Şifre',exact=True)).to_be_visible()
                            assert page.get_by_role('tab').count()==0
                            page.get_by_label('Şifre',exact=True).fill(password)
                            page.get_by_role('button',name='Giriş',exact=True).click()
                            tab=page.get_by_role('tab',name='🧭 AS Control Tower',exact=True)
                            expect(tab).to_be_visible()
                            tab.click()
                            expect(page.get_by_text('🔗 Tekliften tahsilata • Bütünleşik işlem merkezi',exact=True)).to_be_visible()
                            expect(page.locator('[data-testid="stException"]')).to_have_count(0)
                            for label in ['🚚 Satın Alma & Stok','💶 Finans & Nakit','🧪 Kalite & Regülasyon','📊 Yönetici Paneli']:
                                page.get_by_role('tab',name=label,exact=True).click()
                                expect(page.locator('[data-testid="stException"]')).to_have_count(0)
                            overflow=page.evaluate('document.documentElement.scrollWidth > window.innerWidth + 2')
                            assert not overflow, f'{name}: page-wide horizontal overflow'
                            page.screenshot(path=str(output/f'{engine}-{name}.png'),full_page=True)
                            print(f'PASS {engine} {name} {width}x{height}: login, protected tabs, module navigation, no page overflow')
                            context.close()
                        browser.close()
            finally:
                server.terminate()
                server.wait(timeout=15)


if __name__=='__main__':
    main()
