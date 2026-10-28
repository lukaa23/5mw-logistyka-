# ASOLAR v2 — system wielu budów PV

Nowa, osobna wersja aplikacji. **Nie zastępuje i nie zmienia** wersji 1 (katalogi `app/`, `frontend/`, `desktop/` w głównym folderze repozytorium), która działa dalej pod dotychczasowym adresem.

## Stan: etap 1 z 5

| Etap | Zakres | Stan |
|---|---|---|
| 1 | Rejestr budów, przełącznik budów, izolowana przestrzeń danych każdej budowy, konta i role per budowa | **gotowy** |
| 2 | Wgrywanie wielu PDF naraz, lokalny parser (tabele BOM, teksty z rysunków, wzorce), ekran przeglądu propozycji | planowany |
| 3 | Zasilenie budowy zatwierdzonymi danymi: strefy, typy konstrukcji, BOM, stoły/słupy, rzędy | planowany |
| 4 | Moduły operacyjne z v1: rzędy, offline, notatki, zdjęcia, WZ, meldunki, Planimetria | planowany |
| 5 | Docker/Render (osobna usługa), aplikacja desktopowa, dokumentacja | planowany |

## Architektura

```
v2/
  backend/asolar2/
    config.py     adres bazy, folder danych, tryb serwera
    registry.py   rejestr centralny: konta, budowy, członkostwa (rola per budowa), dziennik
    tenancy.py    izolowana przestrzeń każdej budowy
    security.py   hasła PBKDF2, tokeny sesji
    main.py       API
  frontend/src/   React: logowanie, „Moje budowy”, nowa budowa, przełącznik, zakładki budowy, konta
```

**Izolacja danych budów**

- PostgreSQL (serwer): każda budowa ma osobny schemat `proj_<id>` z własnymi tabelami.
- SQLite (lokalnie): każda budowa ma osobny plik `data/projects/proj_<id>.db`.
- Modele budowy są zdefiniowane raz; przy każdym żądaniu SQLAlchemy podstawia schemat konkretnej budowy (`schema_translate_map`), więc zapytanie nie może sięgnąć do tabel innej budowy.
- Rejestr centralny przechowuje tylko konta, listę budów i uprawnienia — żadnych danych budów.
- Usunięcie budowy (po archiwizacji i przepisaniu nazwy) kasuje wyłącznie jej schemat / plik.

**Konta i role**

- Jedno konto na osobę. Administrator tworzy budowy i konta oraz widzi wszystkie budowy.
- W każdej budowie osoba ma rolę *kierownik* albo *brygadzista* (zakładka „Zespół”).
- Osoba spoza zespołu budowy dostaje „nie znaleziono” — nie dowiaduje się o jej istnieniu.
- Uprawnienia są sprawdzane na serwerze przy każdym żądaniu.

## Uruchomienie lokalne

```bash
cd v2/frontend && npm ci && npm run build && cd ..
cd backend && python -m pip install -r requirements-dev.txt
python server.py            # http://127.0.0.1:8770
```

Pierwsze konto administratora: login `kierownik`, hasło `Asolar2026!` (tylko lokalnie — na serwerze wymagane są `ASOLAR_SECRET` i `ASOLAR_ADMIN_PASSWORD`). Dane lokalne: `v2/backend/data/` (lub `ASOLAR_DATA_DIR`).

## Testy

```bash
cd v2/backend && python -m pytest -q      # SQLite; z DATABASE_URL=postgresql://… — PostgreSQL
cd v2/frontend && npm test
```

CI (`.github/workflows/v2-ci.yml`) uruchamia testy backendu na PostgreSQL 16 i SQLite oraz testy frontendu.
