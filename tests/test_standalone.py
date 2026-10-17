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
