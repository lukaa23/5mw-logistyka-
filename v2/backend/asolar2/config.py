"""Konfiguracja ASOLAR v2: baza (SQLite lokalnie / PostgreSQL na serwerze), folder danych, tryb serwera."""
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = Path(os.getenv("ASOLAR_DATA_DIR") or ROOT / "data")
PROJECTS_DIR = DATA_DIR / "projects"
DATA_DIR.mkdir(parents=True, exist_ok=True)
PROJECTS_DIR.mkdir(parents=True, exist_ok=True)


def normalize_database_url(raw: str | None) -> str:
    """postgres:// i postgresql:// (Render) → sterownik psycopg 3; brak wartości → lokalny SQLite."""
    value = (raw or "").strip()
    if not value:
        return f"sqlite:///{DATA_DIR / 'registry.db'}"
    if value.startswith("postgres://"):
        return "postgresql+psycopg://" + value[len("postgres://"):]
    if value.startswith("postgresql://"):
        return "postgresql+psycopg://" + value[len("postgresql://"):]
    return value


DATABASE_URL = normalize_database_url(os.getenv("DATABASE_URL"))
IS_POSTGRES = DATABASE_URL.startswith("postgresql")
SERVER_MODE = IS_POSTGRES or os.getenv("ASOLAR_REQUIRE_PASSWORDS") == "1"

SECRET = os.getenv("ASOLAR_SECRET", "")
if not SECRET:
    if SERVER_MODE:
        raise RuntimeError("Brak zmiennej ASOLAR_SECRET. Wdrożenie serwerowe wymaga własnego, długiego klucza sesji.")
    SECRET = "asolar-v2-local-change-me"

APP_VERSION = "2.0.0-etap1"
