# ASOLAR v2 — system wielu budów PV

Nowa, osobna wersja aplikacji. **Nie zastępuje i nie zmienia** wersji 1 (katalogi `app/`, `frontend/`, `desktop/` w głównym folderze repozytorium), która działa dalej pod dotychczasowym adresem.

## Stan: wersja 2.0.0 — wszystkie etapy gotowe

| Etap | Zakres | Stan |
|---|---|---|
| 1 | Rejestr budów, przełącznik budów, izolowana przestrzeń danych każdej budowy, konta i role per budowa | **gotowy** |
| 2 | Wgrywanie wielu PDF naraz, lokalny parser (tabele BOM, teksty z rysunków, wzorce), ekran przeglądu propozycji | **gotowy** |
| 3 | Zasilenie budowy zatwierdzonymi danymi: strefy, typy konstrukcji, BOM, stoły/słupy, rzędy | **gotowy** |
| 4a | Praca w terenie: montaż i odbiór QA/QC stołów, notatki, zdjęcia, kolejka offline, service worker | **gotowy** |
| 4b | Dostawy WZ wobec zapotrzebowania, stan magazynu, meldunki dzienne | **gotowy** |
| 4c | Planimetria, raport dzienny, pulpit postępu | **gotowy** |
| 5 | Docker/Render (osobna usługa), aplikacja desktopowa, dokumentacja | **gotowy** |

**Dokumentacja:** [instrukcja użytkownika](docs/INSTRUKCJA.md) · [wdrożenie (Render, Docker, desktop)](docs/WDROZENIE.md)

**Wdrożenie (etap 5):** `v2/Dockerfile` (kontekst `v2/`), `v2/render.yaml` (osobny Blueprint: usługa `asolar-v2` + baza `asolar-v2-postgres`), `v2/docker-compose.yml` (v2 + PostgreSQL), aplikacja desktopowa `v2/desktop` (Electron: klient serwera v2 albo serwer na komputerze; tagi `v2.*` budują .exe jako wydanie wstępne). CI uruchamia obraz Docker z testem dymnym (`v2/scripts/smoke_test.py`).

## Architektura

```
v2/
  backend/asolar2/
    config.py     adres bazy, folder danych, tryb serwera
    registry.py   rejestr centralny: konta, budowy, członkostwa (rola per budowa), dziennik
    tenancy.py    izolowana przestrzeń każdej budowy (strefy, dziennik, dokumenty, propozycje)
    pdfparse.py   lokalny parser PDF (pdfplumber) — bez danych wpisanych na sztywno
    cad.py        rysunki DWG/DXF (ezdxf): teksty z warstw, zliczone bloki, geometria SVG do Planimetrii
    imports.py    analiza w tle, scalanie propozycji z wielu plików, decyzje kierownika
    structure.py  zastosowanie/cofnięcie zatwierdzonych propozycji, zapotrzebowanie materiałów
    logistics.py  katalog materiałów, stan magazynu wobec zapotrzebowania
    plans.py      Planimetria: render strony PDF, położenie stołów z warstwy tekstowej rysunku
    report.py     pulpit postępu z prognozą (z założeniami), raport dzienny PDF
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

**Dokumenty PDF i propozycje (etap 2)**

- Zakładka „Dokumenty i import”: wiele PDF naraz (przeciągnij/wybierz, do 60 MB każdy, 20 na żądanie). Pliki trafiają do przestrzeni danej budowy; duplikaty (SHA-256) są pomijane.
- Analiza działa lokalnie w tle: tabele BOM (nagłówki PL/EN/IT/DE, typ konstrukcji z podpisu tabeli), wiersze tekstowe tabel, typy konstrukcji (`1x28`, `1x42+1x28`), strefy, numeracja stołów/trackerów (z pominięciem oznaczeń elektrycznych i rozmiarów śrub), momenty dokręcania, narzędzia.
- Każda propozycja ma źródło (plik, strona, fragment) i pewność. Ten sam element z wielu plików = jedna propozycja z wieloma źródłami; różne ilości tej samej pozycji BOM są oznaczane jako rozbieżność („wymaga potwierdzenia”) i nie wchodzą do zatwierdzania zbiorczego.
- Kierownik zatwierdza, poprawia albo odrzuca; brygadzista ma podgląd. Ponowna analiza nie nadpisuje decyzji ani poprawek. Zatwierdzona strefa od razu trafia do budowy; pozostałe rodzaje zasilą strukturę budowy w etapie 3.
- Ograniczenie: strony zapisane jako obraz (skany) są wykrywane i opisywane jako „wymaga OCR” — OCR nie jest jeszcze wykonywany.

**Struktura budowy (etap 3)**

- Zatwierdzenie propozycji tworzy dane budowy: typ konstrukcji, pozycję BOM typu (ilość na jeden stół), stoły z numeracji (tylko numery odczytane z rysunku — luki nie są dopisywane), komponenty/narzędzia, momenty dokręcania, strefy.
- Pozycja BOM bez typu konstrukcji nie zostanie zastosowana — trzeba uzupełnić typ. Dwie wersje tej samej pozycji z różnymi ilościami nie mogą obie trafić do BOM.
- Cofnięcie decyzji usuwa utworzone dane, o ile nic z nich nie korzysta (np. stoły z przypisaną strefą) — inaczej serwer odmawia z wyjaśnieniem.
- Zakładki: „Konstrukcje i BOM” (typy, słupy na stół, BOM, katalog, momenty), „Stoły i rzędy” (filtry, zaznaczanie i zbiorcze przypisanie strefy/rzędu/typu, ręczne dodanie zakresu), „Zapotrzebowanie” (ilość BOM × liczba stołów, dla budowy lub strefy, eksport CSV).
- Brakujące dane (typ stołu, strefa, liczba słupów, BOM typu) są pokazywane jako „wymaga potwierdzenia” i nie są liczone.
- Nowe kolumny w istniejących przestrzeniach budów są dodawane automatycznie przy starcie (prosta migracja).

**Praca w terenie (etap 4a)**

- Zakładka „Postęp prac”: brygadzista i kierownik oznaczają montaż stołu, kierownik wykonuje odbiór QA/QC (dopiero po montażu; cofnięcie montażu cofa odbiór, z potwierdzeniem).
- Panel stołu: notatki (edycja/usuwanie — autor albo kierownik) i zdjęcia z aparatu telefonu.
- Bez zasięgu: zmiany trafiają do kolejki w IndexedDB (zdjęcia jako bajty), są widoczne od razu jako „czeka na wysłanie” i wysyłane automatycznie po powrocie połączenia. client_id zapobiega duplikatom, client_time zachowuje moment wykonania czynności. Widoki pokazują ostatnią zapisaną kopię danych; service worker uruchamia aplikację bez sieci.
- Stołów z zapisanym postępem, notatkami lub zdjęciami nie można usunąć ani cofnąć ich numeracji.

**Dostawy i meldunki (etap 4b)**

- „Dostawy i magazyn”: przyjęcie WZ (kierownik i brygadzista, także offline), pozycje wybierane z katalogu materiałów budowy (BOM + zatwierdzone komponenty) — dostawa zawsze trafia do bilansu. Edycja i usuwanie WZ: kierownik.
- Stan materiałów: zapotrzebowanie (BOM × stoły) wobec dostarczonych − uszkodzonych; status komplet / brak / poza zapotrzebowaniem, filtr „tylko braki”.
- „Meldunki”: dzienny meldunek brygady (prace, osoby, godziny → rbh, stoły, dziennik QA/QC, zdjęcia). Offline: meldunek i jego zdjęcia czekają w kolejce; zdjęcia trafiają do meldunku po jego client_id.

**Planimetria, pulpit, raport (etap 4c)**

- „Planimetria”: strona rysunku PDF ze znacznikami stołów w kolorze stanu (do montażu / zamontowany / odebrany). Położenie to współrzędne oznaczeń (np. T.48) z warstwy tekstowej rysunku — nic nie jest zgadywane. Kliknięcie znacznika otwiera panel stołu (notatki, zdjęcia). Rysunek-skan wyświetla się bez znaczników, z wyjaśnieniem.
- „Przegląd”: pulpit postępu (zamontowane, odebrane, dziś, braki materiałów, montaż z 14 dni) i prognoza zakończenia liczona z dat montażu — tylko przy danych z ≥ 2 dni, zawsze z wypisanymi założeniami.
- Raport dzienny PDF: liczby dnia, postęp wg stref, zamontowane stoły, meldunki, dziennik QA/QC, notatki, dostawy.

**Rysunki DWG i DXF (2.1.0)**

- W „Dokumenty i import” można wgrywać pliki `.dwg` i `.dxf` razem z PDF (rozpoznawane po zawartości, nie tylko po rozszerzeniu).
- Z rysunku: teksty i atrybuty bloków z warstw (numeracja stołów z nazwą warstwy, strefy, typy konstrukcji, momenty), bloki z liczbą wstawień (np. pale, moduły — jako ilość kontrolna w katalogu; rysunek nie mówi, ile przypada na stół), geometria i położenie oznaczeń w Planimetrii (SVG).
- Propozycje trafiają na ten sam ekran przeglądu co z PDF.
- DXF czytany bezpośrednio. **DWG wymaga konwertera** na serwerze/komputerze: ODA File Converter (bezpłatny), LibreDWG `dwg2dxf` albo własne polecenie w `ASOLAR_DWG_CONVERTER` (szablon z `{input}` i `{output}`). Bez konwertera dokument dostaje komunikat z instrukcją (np. zapisz jako DXF).

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
