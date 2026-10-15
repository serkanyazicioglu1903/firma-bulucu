"""Owner-only preparation of private login settings, without activating them."""
import streamlit as st

from security_admin import current_user
from scripts.private_login_setup import login_settings


def render_private_login_setup():
    user = current_user() or {}
    if user.get('role') != 'ADMIN' or user.get('username') != 'serkan':
        st.session_state.pop('runtime_private_login_settings', None)
        return
    with st.expander('🔐 Serkan hesabı — güvenli giriş kurulumu'):
        st.caption('iPad ve telefondan hazırlanabilir. Bu işlem veritabanını değiştirmez; şirket ayrımını etkinleştirmez.')
        st.warning('Yeni, farklı bir uygulama parolası seçin. Oluşan ayarları ve bu bölümün ekran görüntüsünü paylaşmayın.')
        with st.form('runtime_login_setup_form', clear_on_submit=True):
            password = st.text_input('Yeni uygulama parolası (en az 14 karakter)', type='password', key='runtime_setup_password')
            confirmation = st.text_input('Yeni uygulama parolasını tekrar yaz', type='password', key='runtime_setup_confirmation')
            submitted = st.form_submit_button('Özel giriş ayarlarını hazırla')
        if submitted:
            st.session_state.pop('runtime_private_login_settings', None)
            try:
                st.session_state['runtime_private_login_settings'] = login_settings(password, confirmation)
            except ValueError:
                st.error('Parolalar aynı ve en az 14 karakter olmalı.')
        content = st.session_state.get('runtime_private_login_settings')
        if content:
            st.info('Henüz uygulanmadı. İki ayarı Streamlit → App settings → Secrets alanına ekleyin. Aynı isimli ayar varsa değiştirin; DATABASE_URL dahil diğer ayarları koruyun. Kaydettikten sonra yeni parolayla giriş yapın.')
            st.code(content, language='toml')
            st.caption('Bu çıktı parolanın kendisini içermez; parola özeti ve oturum imzalama anahtarı içerir. Gizli tutun.')
            if st.button('Hazırlanan ayarları bu oturumdan temizle', key='runtime_setup_clear'):
                st.session_state.pop('runtime_private_login_settings', None)
                st.rerun()
