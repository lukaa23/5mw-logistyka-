"""Test dymny działającego serwera ASOLAR v2 (np. obrazu Docker w CI albo wdrożenia).

Użycie:
  python smoke_test.py http://localhost:10000 setup    # tworzy dwie budowy z danymi
  python smoke_test.py http://localhost:10000 verify   # po restarcie: dane są i są rozdzielone

Hasło administratora: zmienna ASOLAR_ADMIN_PASSWORD. Tylko biblioteka standardowa Pythona.
"""
import json
import os
import sys
import time
import urllib.error
import urllib.request

BASE, MODE = sys.argv[1].rstrip("/"), sys.argv[2]
NAMES = ("Smoke A", "Smoke B")


def call(method, path, body=None, token=None, raw=False):
    data = json.dumps(body).encode() if body is not None else None
    request = urllib.request.Request(BASE + path, data=data, method=method)
    if data is not None:
        request.add_header("Content-Type", "application/json")
    if token:
        request.add_header("Authorization", f"Bearer {token}")
    with urllib.request.urlopen(request, timeout=30) as response:
        content = response.read()
        return content if raw else json.loads(content or b"null")


def wait_for_health():
    for _ in range(90):
        try:
            return call("GET", "/api/health")
        except (urllib.error.URLError, ConnectionError):
            time.sleep(2)
    raise SystemExit("Serwer nie odpowiada")


def check(condition, message):
    if not condition:
        raise SystemExit(f"BŁĄD: {message}")
    print(f"ok: {message}")


health = wait_for_health()
check(health["status"] == "ok" and health["version"].startswith("2."), f"health {health}")
token = call("POST", "/api/auth/login", {"username": "kierownik", "password": os.environ["ASOLAR_ADMIN_PASSWORD"]})["token"]
check(b"<div id=\"root\">" in call("GET", "/", raw=True), "frontend serwowany pod /")

if MODE == "setup":
    check(health["isolation"] == "schema-per-project" if health["database"] == "postgresql" else True, "izolacja: schemat na budowę")
    for index, name in enumerate(NAMES):
        project = call("POST", "/api/projects", {"name": name, "location": "CI", "capacity_mw": 1}, token)
        base = f"/api/projects/{project['id']}"
        call("POST", f"{base}/zones", {"name": f"Strefa {name}"}, token)
        call("POST", f"{base}/tables/range", {"prefix": "T", "first": 1, "last": 3 + index}, token)
        table = call("GET", f"{base}/tables", token=token)[0]
        call("PATCH", f"{base}/tables/{table['id']}/progress", {"built": True}, token)
        call("POST", f"{base}/tables/{table['id']}/notes", {"text": f"notatka {name}"}, token)
    pdf = call("GET", f"{base}/reports/daily", token=token, raw=True)
    check(pdf.startswith(b"%PDF"), "raport dzienny PDF")
    print("setup zakończony")
elif MODE == "verify":
    projects = {p["name"]: p for p in call("GET", "/api/projects", token=token)}
    for index, name in enumerate(NAMES):
        check(name in projects, f"budowa {name} przetrwała restart")
        base = f"/api/projects/{projects[name]['id']}"
        tables = call("GET", f"{base}/tables", token=token)
        check(len(tables) == 3 + index, f"{name}: {3 + index} stołów (dane nie mieszają się między budowami)")
        check(tables[0]["built"] and tables[0]["notes"] == 1, f"{name}: postęp i notatka zapisane")
        zones = [z["name"] for z in call("GET", f"{base}/zones", token=token)]
        check(zones == [f"Strefa {name}"], f"{name}: tylko własna strefa")
    print("verify zakończony")
else:
    raise SystemExit("Tryb: setup albo verify")
