"""Guardrail tests: local-only test connections must never weaken Supabase TLS."""
import os
import unittest
from unittest.mock import patch

from scripts.postgres_connection import sslmode_for


class SecurePostgresTransportTests(unittest.TestCase):
    def test_production_always_uses_tls(self):
        with patch.dict(os.environ, {"CT_LOCAL_POSTGRES_TEST": "0"}):
            for url in (
                "postgresql://ct_ci:dummy@127.0.0.1:5432/ct_ci_control_tower",
                "postgresql://operator:private@db.pooler.supabase.com:6543/postgres",
            ):
                self.assertEqual(sslmode_for(url), "require")

    def test_disposable_local_ci_allows_non_tls(self):
        with patch.dict(os.environ, {"CT_LOCAL_POSTGRES_TEST": "1"}):
            self.assertEqual(
                sslmode_for(
                    "postgresql://ct_ci:ci-dummy@127.0.0.1:5432/ct_ci_control_tower"
                ),
                "disable",
            )

    def test_local_toggle_cannot_disable_supabase_tls(self):
        with patch.dict(os.environ, {"CT_LOCAL_POSTGRES_TEST": "1"}):
            for url in (
                "postgresql://ct_ci:pw@db.supabase.co:5432/ct_ci_control_tower",
                "postgresql://ct_ci:pw@127.0.0.1:5432/postgres",
                "postgresql://admin:pw@127.0.0.1:5432/ct_ci_control_tower",
                "postgresql://ct_ci:pw@127.0.0.1:6543/ct_ci_control_tower",
                "postgresql://ct_ci:pw@192.168.1.1:5432/ct_ci_control_tower",
                "not-a-db",
            ):
                with self.subTest(url=url):
                    self.assertEqual(sslmode_for(url), "require")


if __name__ == "__main__":
    unittest.main()
