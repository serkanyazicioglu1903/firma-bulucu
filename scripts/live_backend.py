"""Fail-closed runtime selection for AS Control Tower's PostgreSQL cutover.

Once DATABASE_URL is configured (as in the user's Supabase Streamlit app), the
business interface uses ct_app. A failed connection NEVER falls back to SQLite.
The old SQLite file is never deleted or migrated implicitly.
"""
import os
from pathlib import Path

import streamlit as st

from scripts.staging_transaction_smoke import validate_test_url


def postgres_url():
    """Secret only, never user-controlled URL fields or query parameters."""
    explicit = str(os.environ.get("AS_CONTROL_TOWER_BACKEND", "")).lower().strip()
    if explicit == "sqlite":
        return ""
    try:
        secret = str(st.secrets.get("DATABASE_URL", "") or "").strip()
    except Exception:
        secret = ""
    # Local CI may supply secrets through environment instead of Streamlit.
    secret = secret or str(os.environ.get("DATABASE_URL", "") or "").strip()
    if not secret:
        return ""
    if not validate_test_url(secret):
        return "INVALID_POSTGRES_URL"
    return secret


def ready_for_live(url, sqlite_db_path):
    """Preflight that blocks silent loss of pre-existing SQLite business data."""
    if url == "INVALID_POSTGRES_URL" or not validate_test_url(url):
        return "invalid_url"
    from scripts.staging_validate import validate_staging_structure
    try:
        status, _ = validate_staging_structure(url, schema="ct_app")
        if status != "ok":
            return "schema_mismatch"
    except Exception:
        return "connection_failed"
    # The user's prior preflight found 0 rows, but recheck during cutover.
    if sqlite_db_path and Path(sqlite_db_path).is_file():
        from scripts.postgres_migration_readiness import read_sqlite_source_counts
        try:
            counts = read_sqlite_source_counts(sqlite_db_path)
            if sum(counts.values()):
                return "sqlite_data_present"
        except Exception:
            return "sqlite_integrity_unknown"
    return "ready"
