# ASOLAR v2 — wdrożenie

v2 to **osobna usługa z osobną bazą**. Wersja 1 (`asolar-eset-tracker` na Render, główny `Dockerfile` i `render.yaml`) działa dalej bez zmian.

## Render (zalecane)

1. Render → **New → Blueprint** → wybierz to repozytorium → **Blueprint Path: `v2/render.yaml`**.
2. Render utworzy:
   - bazę `asolar-v2-postgres` (PostgreSQL 16) — każda budowa dostaje w niej własny schemat `proj_<id>`,
   - usługę `asolar-v2` (Docker, kontekst `v2/`, health check `/api/health`).
3. W formularzu podaj **ASOLAR_ADMIN_PASSWORD** (hasło pierwszego administratora `kierownik`). `ASOLAR_SECRET` generuje Render.
4. Po wdrożeniu: `https://<nazwa>.onrender.com/api/health` → `{"status":"ok","version":"2.0.0","database":"postgresql","isolation":"schema-per-project"}`.

`buildFilter` w blueprincie powoduje, że zmiany poza `v2/` nie przebudowują usługi v2.

Darmowy plan Render usypia usługę po bezczynności (pierwsze wejście ~1 min). Darmowa baza Render ma ograniczony czas życia — do pracy produkcyjnej wybierz płatny plan bazy i włącz kopie zapasowe w panelu Render.

## Zmienne środowiskowe

| Zmienna | Wymagana | Opis |
|---|---|---|
| `DATABASE_URL` | serwer | PostgreSQL (`postgres://…` jest akceptowane). Brak = SQLite w `ASOLAR_DATA_DIR`. |
| `ASOLAR_SECRET` | serwer | Długi losowy klucz podpisu sesji. Bez niego serwer z PostgreSQL odmawia startu. |
| `ASOLAR_ADMIN_PASSWORD` | pierwszy start | Hasło pierwszego administratora (tworzony tylko, gdy w bazie nie ma kont). |
| `ASOLAR_ADMIN_USERNAME` | nie | Login pierwszego administratora (domyślnie `kierownik`). |
| `ASOLAR_DATA_DIR` | nie | Folder danych lokalnych (SQLite: `registry.db` + `projects/proj_<id>.db`). |
| `PORT`, `ASOLAR_HOST` | nie | Port (domyślnie 8770) i adres nasłuchu (w Dockerze `0.0.0.0`). |
| `ASOLAR_REQUIRE_PASSWORDS=1` | nie | Tryb serwerowy także na SQLite (wymaga sekretu i hasła administratora). |

## Docker na własnym serwerze

```bash
cd v2
ASOLAR_SECRET=$(openssl rand -hex 32) ASOLAR_ADMIN_PASSWORD='…' docker compose up --build -d
```

Aplikacja: `http://<serwer>:8770`. Do pracy telefonów offline (PWA) potrzebny jest **HTTPS** — postaw przed kontenerem reverse proxy z certyfikatem (np. Caddy).

## Lokalnie (bez Dockera)

```bash
cd v2/frontend && npm ci && npm run build
cd ../backend && python -m pip install -r requirements.txt
python server.py    # http://127.0.0.1:8770, login kierownik / Asolar2026!
```

## Aplikacja desktopowa (Windows)

Budowana przez GitHub Actions (`.github/workflows/v2-windows-release.yml`) po wypchnięciu tagu `v2.*` — pliki `.exe` trafiają do wydania wstępnego (pre-release), żeby nie zastąpić wydania v1. Lokalnie:

```bash
cd v2/frontend && npm ci && npm run build
cd ../desktop && npm ci && npm test && npx electron-builder --win nsis portable
```

## Aktualizacje schematu bazy

Przy starcie serwer uzupełnia przestrzeń każdej budowy o nowe tabele i kolumny (migracja addytywna). Nie trzeba uruchamiać skryptów ręcznie.

## Testy i CI

`.github/workflows/v2-ci.yml`: backend na PostgreSQL 16 i SQLite, frontend, aplikacja desktopowa oraz obraz Docker z testem dymnym (`v2/scripts/smoke_test.py`: dwie budowy, restart kontenera, sprawdzenie trwałości i izolacji).
