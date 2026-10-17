"""Klucz do podpisywania sesji: ze zmiennej środowiskowej albo losowy i trwały (data/secret.key)."""

import os
import secrets
from pathlib import Path

MIN_SECRET_LENGTH = 16
PLACEHOLDER_SECRETS = {
    "asolar-local-change-me",
    "zmien-ten-klucz-przed-wdrozeniem",
    "zmien-to",
    "changeme",
}


def is_strong_secret(value):
    value = (value or "").strip()
    return len(value) >= MIN_SECRET_LENGTH and value.lower() not in PLACEHOLDER_SECRETS


def load_secret(environ, data_dir):
    """Zwraca klucz sesji.

    1. ASOLAR_SECRET, jeśli jest długi i nie jest przykładową wartością;
    2. w przeciwnym razie klucz zapisany w data/secret.key (tworzony losowo przy pierwszym uruchomieniu).
    Dzięki temu w kodzie nie ma stałego klucza, który pozwalałby podrobić sesję.
    """
    configured = (environ.get("ASOLAR_SECRET") or "").strip()
    if is_strong_secret(configured):
        return configured
    path = Path(data_dir) / "secret.key"
    try:
        stored = path.read_text(encoding="utf8").strip()
        if is_strong_secret(stored):
            return stored
    except OSError:
        pass
    fresh = secrets.token_hex(32)
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:
        # inny proces zdążył zapisać klucz — używamy jego wersji
        stored = path.read_text(encoding="utf8").strip()
        if is_strong_secret(stored):
            return stored
        path.write_text(fresh, encoding="utf8")
        return fresh
    with os.fdopen(descriptor, "w", encoding="utf8") as target:
        target.write(fresh)
    return fresh
