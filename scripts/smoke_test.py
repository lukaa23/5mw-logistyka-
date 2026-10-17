"""Test dymny wdrożenia: uruchomiony serwer (np. kontener Docker jak na Render) + PostgreSQL.

Użycie:
  python scripts/smoke_test.py http://localhost:10000 setup    # kierownik + brygadzista, WebSocket, zdjęcia
  python scripts/smoke_test.py http://localhost:10000 verify   # po restarcie kontenera: dane i hasła zachowane

Hasła startowe są czytane ze zmiennych ASOLAR_*_PASSWORD (te same co w kontenerze).
Wymaga pakietu `websockets` dla testu powiadomień w czasie rzeczywistym.
"""
import asyncio
import json
import os
import sys
import time
import urllib.error
import urllib.request
import uuid
from datetime import datetime, timedelta, timezone

BASE = sys.argv[1].rstrip("/")
PHASE = sys.argv[2] if len(sys.argv) > 2 else "setup"
VARIANTS = ("1x28", "1x42", "1x56", "1x70", "1x42+1x28", "1x56+1x28", "1x56+1x42")
ZONE_NAME = "Strefa SMOKE — północ"
PHONE_TIME = (datetime.now(timezone.utc) - timedelta(hours=2)).replace(microsecond=0)
PNG = b"\x89PNG\r\n\x1a\n" + b"smoke" * 20


def request(method, path, token=None, body=None, form=None, expect=200, raw=False):
    headers = {}
    data = None
    if token:
        headers["Authorization"] = f"Bearer {token}"
    if body is not None:
        data = json.dumps(body).encode()
        headers["Content-Type"] = "application/json"
    if form is not None:
        boundary = uuid.uuid4().hex
        parts = []
        for name, value in form.items():
            if isinstance(value, tuple):
                filename, content, mime = value
                parts.append(f'--{boundary}\r\nContent-Disposition: form-data; name="{name}"; filename="{filename}"\r\nContent-Type: {mime}\r\n\r\n'.encode() + content + b"\r\n")
            else:
                parts.append(f'--{boundary}\r\nContent-Disposition: form-data; name="{name}"\r\n\r\n{value}\r\n'.encode())
        data = b"".join(parts) + f"--{boundary}--\r\n".encode()
        headers["Content-Type"] = f"multipart/form-data; boundary={boundary}"
    req = urllib.request.Request(BASE + path, data=data, method=method, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=30) as response:
            status, payload, ctype = response.status, response.read(), response.headers.get("Content-Type", "")
    except urllib.error.HTTPError as error:
        status, payload, ctype = error.code, error.read(), error.headers.get("Content-Type", "")
    assert status == expect, f"{method} {path}: oczekiwano {expect}, otrzymano {status}: {payload[:300]!r}"
    if raw:
        return payload, ctype
    return json.loads(payload) if payload and "json" in ctype else payload


def check(label, condition):
    if not condition:
        raise AssertionError(label)
    print(f"  ✓ {label}")


def login(username, env_name):
    return request("POST", "/api/auth/login", body={"username": username, "password": os.environ[env_name]})["token"]


def wait_for_health(timeout=90):
    started = time.time()
    while time.time() - started < timeout:
        try:
            return request("GET", "/api/health")
        except Exception:
            time.sleep(2)
    raise SystemExit("Serwer nie odpowiada na /api/health")


async def expect_ws_event(token, action, event_name):
    import websockets
    url = BASE.replace("http", "ws", 1) + f"/ws?token={token}"
    async with websockets.connect(url) as ws:
        await ws.send("ping")
        assert await asyncio.wait_for(ws.recv(), 10) == "pong"
        await asyncio.get_running_loop().run_in_executor(None, action)
        deadline = time.time() + 10
        while time.time() < deadline:
            message = await asyncio.wait_for(ws.recv(), 10)
            if message != "pong" and json.loads(message).get("event") == event_name:
                return True
    return False


def setup():
    health = wait_for_health()
    check(f"serwer działa, wersja {health['version']}", health["status"] == "ok")
    check(f"baza danych: {health['database']}", health["database"] == "postgresql" or os.environ.get("SMOKE_ALLOW_SQLITE") == "1")
    check("pliki w bazie, WebSocket włączony", health["file_storage"] == "database" and health["realtime"] == "websocket")

    html, ctype = request("GET", "/", raw=True)
    check("strona główna serwuje aplikację", b'id="root"' in html and "text/html" in ctype)
    _, ctype = request("GET", "/sw.js", raw=True)
    check("service worker jako JavaScript", "javascript" in ctype)
    manifest = request("GET", "/manifest.json")
    check("manifest PWA (standalone, ikony PNG)", manifest["display"] == "standalone" and any(icon["src"] == "/icon-512.png" for icon in manifest["icons"]))
    request("GET", "/icon-192.png", raw=True)
    request("GET", "/assets/nie-istnieje.js", expect=404, raw=True)
    check("brakujący skrypt → 404, nie HTML", True)
    request("POST", "/api/auth/login", body={"username": "kierownik", "password": "zle-haslo"}, expect=401)

    manager = login("kierownik", "ASOLAR_MANAGER_PASSWORD")
    foreman = login("brygadzista1", "ASOLAR_FOREMAN1_PASSWORD")
    login("brygadzista2", "ASOLAR_FOREMAN2_PASSWORD")
    check("logowanie trzech ról", True)
    request("GET", "/api/users", token=foreman, expect=403)
    check("brygadzista nie zarządza użytkownikami", True)

    project = next(item for item in request("GET", "/api/projects", token=manager) if item["name"] == "RF-GIULIETTA")
    documents = request("GET", f"/api/documents?project_id={project['id']}", token=manager)
    check("10 zatwierdzonych dokumentów źródłowych w bazie", sum(item["approved_source"] for item in documents) == 10)

    zone = request("POST", "/api/tracker-zones", token=foreman, body={"project_id": project["id"], "name": ZONE_NAME})
    counts = {"1x28": 2, "1x56+1x42": 1}
    request("PUT", f"/api/tracker-zones/{zone['id']}/config", token=foreman, body={"items": [{"variant_code": code, "row_count": counts.get(code, 0)} for code in VARIANTS]})
    rows = [row for row in request("GET", f"/api/projects/{project['id']}/operational-rows", token=manager) if row["zone_id"] == zone["id"]]
    check("strefa z wariantem łączonym generuje 3 rzędy", [row["variant_name"] for row in rows] == ["1x28", "1x28", "1x56+1x42"])

    row = rows[2]
    got_event = asyncio.run(expect_ws_event(manager, lambda: request("PATCH", f"/api/rows/{row['id']}", token=foreman, body={"built": True, "client_time": PHONE_TIME.isoformat()}), "row.changed"))
    check("kierownik dostaje powiadomienie WebSocket o zmianie brygadzisty", got_event)
    request("PATCH", f"/api/rows/{row['id']}", token=foreman, body={"qc_checked": True}, expect=403)
    request("PATCH", f"/api/rows/{row['id']}", token=manager, body={"qc_checked": True})
    request("POST", f"/api/rows/{row['id']}/move", token=foreman, body={"direction": "up"})

    form = {"file": ("aparat.jpg", PNG, "image/jpeg"), "client_id": "smoke-photo-1", "client_time": PHONE_TIME.isoformat()}
    first = request("POST", f"/api/row/{row['id']}/photos", token=foreman, form=form)
    again = request("POST", f"/api/row/{row['id']}/photos", token=foreman, form=form)
    check("zdjęcie z kolejki offline nie jest dublowane (client_id)", again.get("deduplicated") and again["id"] == first["id"])
    request("POST", f"/api/rows/{row['id']}/notes", token=foreman, body={"text": "Notatka z testu wdrożenia", "client_id": "smoke-note-1"})

    status = request("GET", f"/api/projects/{project['id']}/bom-delivery-status", token=manager)
    check("dostawy BOM startują od zera", all(item["delivered"] == 0 for item in status["items"]))
    report, ctype = request("GET", f"/api/reports/daily?project_id={project['id']}", token=manager, raw=True)
    check("raport dzienny PDF", report.startswith(b"%PDF"))
    print("SETUP OK")


def verify():
    wait_for_health()
    manager = login("kierownik", "ASOLAR_MANAGER_PASSWORD")
    check("po restarcie hasło kierownika działa (bez resetu)", bool(manager))
    project = next(item for item in request("GET", "/api/projects", token=manager) if item["name"] == "RF-GIULIETTA")
    zones = [zone for zone in request("GET", f"/api/projects/{project['id']}/tracker-zones", token=manager) if zone["name"] == ZONE_NAME]
    check("strefa przetrwała restart", len(zones) == 1)
    rows = [row for row in request("GET", f"/api/projects/{project['id']}/operational-rows", token=manager) if row["zone_id"] == zones[0]["id"]]
    combined = next(row for row in rows if row["variant_name"] == "1x56+1x42")
    check("status, odbiór QC i kolejność przetrwały restart", combined["built"] and combined["qc_checked"] and combined["code"] == "2")
    built_at = datetime.fromisoformat(str(combined["built_at"])).replace(tzinfo=timezone.utc)
    check("czas zmiany z telefonu zapisany (nie czas synchronizacji)", built_at < datetime.now(timezone.utc) - timedelta(minutes=90))
    photos = request("GET", f"/api/row/{combined['id']}/photos", token=manager)
    content, _ = request("GET", photos[0]["url"], token=manager, raw=True)
    check("zdjęcie przetrwało restart (zapis w bazie)", len(photos) == 1 and content == PNG)
    notes = request("GET", f"/api/rows/{combined['id']}/notes", token=manager)
    check("notatka przetrwała restart", notes[0]["text"] == "Notatka z testu wdrożenia")
    print("VERIFY OK")


if __name__ == "__main__":
    {"setup": setup, "verify": verify}[PHASE]()
