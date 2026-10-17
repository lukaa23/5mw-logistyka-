"""Testy bez FastAPI i SQLAlchemy: adres bazy, hasła startowe, hasze, integralność źródeł.

Uruchomienie: python -m unittest tests.test_standalone
"""
import hashlib
import importlib.util
import json
import sys
import types
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def load_module(name, relative):
    spec = importlib.util.spec_from_file_location(name, ROOT / relative)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


dburl = load_module("asolar_dburl", "app/dburl.py")
lan = load_module("asolar_lan", "app/lan.py")
throttle = load_module("asolar_throttle", "app/throttle.py")
secrets_store = load_module("asolar_secrets_store", "app/secrets_store.py")


def load_auth_functions():
    """Ładuje tylko czyste funkcje z auth.py, bez zależności od FastAPI."""
    source = (ROOT / "app/auth.py").read_text(encoding="utf8")
    start = source.index("MIN_PASSWORD_LENGTH")
    end = source.index("def create_token")
    namespace = {}
    prelude = "import base64, hashlib, hmac, json, os, secrets, time\n"
    exec(prelude + source[start:end], namespace)
    return types.SimpleNamespace(**namespace)


auth = load_auth_functions()


class DatabaseUrlTest(unittest.TestCase):
    def test_default_is_sqlite_file(self):
        self.assertEqual(dburl.normalize_database_url(None, "/tmp/a.db"), "sqlite:////tmp/a.db")
        self.assertEqual(dburl.normalize_database_url("   ", "/tmp/a.db"), "sqlite:////tmp/a.db")

    def test_postgres_schemes_use_psycopg3(self):
        self.assertEqual(dburl.normalize_database_url("postgres://u:p@h:5432/db"), "postgresql+psycopg://u:p@h:5432/db")
        self.assertEqual(dburl.normalize_database_url("postgresql://u:p@h/db?sslmode=require"), "postgresql+psycopg://u:p@h/db?sslmode=require")

    def test_explicit_driver_and_sqlite_are_untouched(self):
        for url in ("postgresql+psycopg://u:p@h/db", "postgresql+psycopg2://u:p@h/db", "sqlite:///x.db"):
            self.assertEqual(dburl.normalize_database_url(url), url)

    def test_missing_default_is_an_error(self):
        with self.assertRaises(ValueError):
            dburl.normalize_database_url(None)


class LanAddressTest(unittest.TestCase):
    def test_keeps_only_private_ipv4_without_loopback_and_link_local(self):
        found = lan.private_ipv4(["127.0.0.1", "169.254.10.2", "192.168.0.15", "10.0.0.7", "8.8.8.8", "::1", "fe80::1", "0.0.0.0", "nie-ip", "192.168.0.15", "172.16.4.9"])
        self.assertEqual(found, ["10.0.0.7", "172.16.4.9", "192.168.0.15"])

    def test_urls_use_the_given_port(self):
        self.assertEqual(lan.lan_urls(8765, ["192.168.1.20", "127.0.0.1"]), ["http://192.168.1.20:8765"])
        self.assertEqual(lan.lan_urls(8765, []), [])


class LoginThrottleTest(unittest.TestCase):
    def make(self, **kwargs):
        self.now = 1000.0
        return throttle.LoginThrottle(clock=lambda: self.now, **kwargs)

    def test_blocks_after_max_failures_and_releases_after_window(self):
        limiter = self.make(max_failures=3, window_seconds=600)
        for _ in range(2):
            limiter.failure("1.1.1.1")
        self.assertEqual(limiter.retry_after("1.1.1.1"), 0)
        limiter.failure("1.1.1.1")
        self.assertGreater(limiter.retry_after("1.1.1.1"), 0)
        self.assertEqual(limiter.retry_after("2.2.2.2"), 0)
        self.now += 601
        self.assertEqual(limiter.retry_after("1.1.1.1"), 0)

    def test_success_clears_failures(self):
        limiter = self.make(max_failures=2)
        limiter.failure("a"); limiter.success("a"); limiter.failure("a")
        self.assertEqual(limiter.retry_after("a"), 0)

    def test_memory_is_bounded(self):
        limiter = self.make(max_keys=5)
        for index in range(50):
            self.now += 1
            limiter.failure(f"ip-{index}")
        self.assertLessEqual(len(limiter._failures), 5)

    def test_forwarded_header_is_trusted_only_from_local_proxy(self):
        self.assertEqual(throttle.client_ip("127.0.0.1", "9.9.9.9, 5.6.7.8"), "5.6.7.8")
        self.assertEqual(throttle.client_ip("::1", "5.6.7.8"), "5.6.7.8")
        self.assertEqual(throttle.client_ip("203.0.113.5", "1.2.3.4"), "203.0.113.5")
        self.assertEqual(throttle.client_ip(None, None), "unknown")


class SessionSecretTest(unittest.TestCase):
    def test_strong_environment_secret_is_used(self):
        import tempfile
        with tempfile.TemporaryDirectory() as folder:
            self.assertEqual(secrets_store.load_secret({"ASOLAR_SECRET": "x" * 32}, folder), "x" * 32)
            self.assertFalse((Path(folder) / "secret.key").exists())

    def test_missing_short_or_placeholder_secret_gets_random_persistent_key(self):
        import os
        import tempfile
        for configured in ({}, {"ASOLAR_SECRET": "krotki"}, {"ASOLAR_SECRET": "zmien-ten-klucz-przed-wdrozeniem"}, {"ASOLAR_SECRET": "asolar-local-change-me"}):
            with tempfile.TemporaryDirectory() as folder:
                first = secrets_store.load_secret(configured, folder)
                self.assertGreaterEqual(len(first), 32)
                self.assertNotIn(first, secrets_store.PLACEHOLDER_SECRETS)
                self.assertEqual(secrets_store.load_secret(configured, folder), first)
                if os.name == "posix":
                    self.assertEqual((Path(folder) / "secret.key").stat().st_mode & 0o077, 0)
        with tempfile.TemporaryDirectory() as one, tempfile.TemporaryDirectory() as two:
            self.assertNotEqual(secrets_store.load_secret({}, one), secrets_store.load_secret({}, two))


class StarterPasswordTest(unittest.TestCase):
    def test_password_comes_from_environment(self):
        self.assertEqual(auth.initial_password("ASOLAR_MANAGER_PASSWORD", {"ASOLAR_MANAGER_PASSWORD": "  Dlugie-haslo-1  "}), ("Dlugie-haslo-1", False))

    def test_missing_or_short_password_is_generated_and_random(self):
        first, generated = auth.initial_password("ASOLAR_MANAGER_PASSWORD", {})
        second, _ = auth.initial_password("ASOLAR_MANAGER_PASSWORD", {"ASOLAR_MANAGER_PASSWORD": "krotkie"})
        self.assertTrue(generated)
        self.assertGreaterEqual(len(first), 12)
        self.assertNotEqual(first, second)

    def test_three_starter_accounts_and_variables(self):
        self.assertEqual([item[0] for item in auth.STARTER_ACCOUNTS], ["kierownik", "brygadzista1", "brygadzista2"])
        self.assertEqual([item[1] for item in auth.STARTER_ACCOUNTS], ["ASOLAR_MANAGER_PASSWORD", "ASOLAR_FOREMAN1_PASSWORD", "ASOLAR_FOREMAN2_PASSWORD"])
        self.assertEqual([item[3] for item in auth.STARTER_ACCOUNTS], ["kierownik", "brygadzista", "brygadzista"])

    def test_hash_round_trip_and_no_plaintext(self):
        encoded = auth.hash_password("Tajne-haslo-123")
        self.assertNotIn("Tajne-haslo-123", encoded)
        self.assertTrue(auth.verify_password("Tajne-haslo-123", encoded))
        self.assertFalse(auth.verify_password("inne", encoded))
        self.assertFalse(auth.verify_password("x", "uszkodzony"))
        self.assertNotEqual(auth.hash_password("a" * 10), auth.hash_password("a" * 10))


class SourceIntegrityTest(unittest.TestCase):
    def test_manifest_hashes_match_files(self):
        manifest = json.loads((ROOT / "project_sources/source-manifest.json").read_text(encoding="utf8"))
        self.assertEqual(len(manifest["documents"]), 10)
        for entry in manifest["documents"]:
            digest = hashlib.sha256((ROOT / "project_sources" / entry["filename"]).read_bytes()).hexdigest()
            self.assertEqual(digest, entry["sha256"], entry["filename"])

    def test_no_production_passwords_in_frontend_sources(self):
        for path in (ROOT / "frontend/src").rglob("*.js*"):
            text = path.read_text(encoding="utf8")
            for secret in ("Asolar2026!", "Brygada2026!", "Magazyn2026!"):
                self.assertNotIn(secret, text, f"{path.name} zawiera hasło")


if __name__ == "__main__":
    unittest.main()
