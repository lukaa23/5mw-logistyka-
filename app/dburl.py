"""Normalizacja adresu bazy danych (SQLite lokalnie, PostgreSQL na serwerze)."""

import os
from pathlib import Path


def normalize_database_url(raw: str | None, default_sqlite_path: Path | str | None = None) -> str:
    """Zwraca adres zrozumiały dla SQLAlchemy.

    - brak wartości: lokalny plik SQLite;
    - postgres:// i postgresql:// (tak podają je Render i Heroku) → postgresql+psycopg:// (psycopg 3);
    - adresy z jawnym sterownikiem oraz sqlite:// pozostają bez zmian.
    """
    value = (raw or "").strip()
    if not value:
        if default_sqlite_path is None:
            raise ValueError("Brak DATABASE_URL i domyślnej ścieżki SQLite")
        return f"sqlite:///{default_sqlite_path}"
    if value.startswith("postgres://"):
        return "postgresql+psycopg://" + value[len("postgres://"):]
    if value.startswith("postgresql://"):
        return "postgresql+psycopg://" + value[len("postgresql://"):]
    return value


def database_url_from_env(default_sqlite_path: Path | str) -> str:
    return normalize_database_url(os.getenv("DATABASE_URL"), default_sqlite_path)
