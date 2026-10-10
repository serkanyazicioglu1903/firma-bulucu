"""Secure PostgreSQL TLS selection for production and disposable local CI.

Production connections always require TLS. Only an explicitly enabled,
dedicated loopback CI database may use an unencrypted Docker service.
Never set CT_LOCAL_POSTGRES_TEST in Streamlit or on Supabase.
"""
import os
from urllib.parse import urlsplit

CI_DATABASE = "ct_ci_control_tower"
CI_USER = "ct_ci"


def sslmode_for(url):
    """Return 'disable' only for a deliberately isolated loopback CI database."""
    if os.environ.get("CT_LOCAL_POSTGRES_TEST") == "1":
        try:
            parsed = urlsplit(str(url or ""))
            if (parsed.scheme in ("postgres", "postgresql")
                    and parsed.hostname in ("localhost", "127.0.0.1")
                    and parsed.path == "/" + CI_DATABASE
                    and parsed.username == CI_USER
                    and parsed.port == 5432):
                return "disable"
        except (ValueError, TypeError):
            pass
    return "require"
