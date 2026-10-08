"""The public Streamlit URL must never render business tabs before login."""
from pathlib import Path

from streamlit.testing.v1 import AppTest


def test_unauthenticated_user_only_sees_login():
    app = AppTest.from_file(str(Path(__file__).resolve().parents[1] / "app.py"), default_timeout=60)
    app.run()
    assert not app.exception, app.exception
    assert not app.tabs, "Business tabs must be hidden until authentication"
    assert any("AS Control Tower Giriş" in x.value for x in app.markdown)
    assert any("Kullanıcı adı" in x.label for x in app.text_input)
    assert any("Şifre" in x.label for x in app.text_input)


def test_authenticated_user_sees_app():
    app = AppTest.from_file(str(Path(__file__).resolve().parents[1] / "app.py"), default_timeout=60)
    app.session_state["ct_user"] = {
        "username": "ci-admin",
        "display_name": "CI Admin",
        "role": "ADMIN",
    }
    app.session_state["ct_session_id"] = "ci-session"
    app.run()
    assert not app.exception, app.exception
    assert len(app.tabs) >= 3
