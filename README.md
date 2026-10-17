# ASOLAR ESET Tracker Manager

[![CI — PostgreSQL i Docker](https://github.com/lukaa23/5mw-logistyka-/actions/workflows/ci.yml/badge.svg)](https://github.com/lukaa23/5mw-logistyka-/actions/workflows/ci.yml) [![Wdróż na Render](https://render.com/images/deploy-to-render-button.svg)](https://render.com/deploy?repo=https://github.com/lukaa23/5mw-logistyka-)

Responsywna aplikacja PWA do konfiguracji trackerów ESET, wyliczania zapotrzebowania projektowego, prowadzenia meldunków brygadzisty i kontroli QA/QC na farmie PV.

## Praca wieloosobowa klient–serwer

W trybie zespołowym wszystkie telefony i komputery otwierają jeden adres HTTPS. FastAPI jest serwerem aplikacji, PostgreSQL przechowuje wspólne dane oraz nowe zdjęcia i dokumenty, a WebSocket natychmiast informuje pozostałe urządzenia o zmianach. Frontend automatycznie ponawia połączenie, ma dodatkowe odświeżanie co 15 sekund i kolejkę zapisów na czas utraty zasięgu.

SQLite pozostaje dostępny do pracy lokalnej. Na hostingu należy ustawić `DATABASE_URL` do PostgreSQL, aby restart kontenera nie usuwał danych. Zdjęcia i PDF wgrywane przez użytkowników są zapisywane w bazie, więc nie zależą od nietrwałego dysku darmowej usługi.

## Konfiguracja i zapotrzebowanie

Projekt korzysta z siedmiu wariantów. Podstawowe to `1x28`, `1x42`, `1x56` i `1x70`, a łączone to `1x42+1x28`, `1x56+1x28` i `1x56+1x42`. Użytkownik tworzy dowolną liczbę nazwanych stref i w każdej wpisuje liczbę rzędów każdego wariantu. System automatycznie generuje osobne, kolejno numerowane rzędy oraz pokazuje:

- listę elementów potrzebnych na pojedynczy rząd;
- sumę dla liczby rzędów danego wariantu;
- sumę dla całego projektu oraz osobny, przełączany widok każdej strefy;
- słupy napędowe, nienapędowe i amortyzatorów;
- podstawy, obudowy łożysk, łożyska polimerowe i reduktory obrotowe;
- rury torsyjne z rozróżnieniem typu, długości i grubości;
- płatwie, elementy amortyzatorów, TCU i odbiornik bezprzewodowy;
- zestawy M10, M12, M14, M16 i M18 wraz z podkładkami oraz momentami dokręcania.

Wariant łączony jest liczony jako dokładna suma dwóch odpowiednich, zatwierdzonych BOM-ów podstawowych. Program nie odejmuje ani nie dodaje części wspólnych, których dokumentacja nie definiuje.

Widok operacyjny pozwala oznaczać każdy wygenerowany rząd jako zbudowany i odebrany QA/QC, prowadzić trwałą historię notatek, robić i przypisywać wiele zdjęć bezpośrednio aparatem telefonu oraz ustawiać rzeczywistą kolejność rzędów przyciskami Góra/Dół. Każdy wpis pamięta autora i czas, a karta rzędu pokazuje ostatnią osobę, która wprowadziła zmianę. Przyciski „Wszystkie”, „Tylko do zrobienia”, „Zbudowane” i „Notatki / zdjęcia” przyspieszają pracę na telefonie. Kolejność oraz cała pamięć rzędu są zapisywane w bazie i synchronizowane między urządzeniami. Zmniejszenie liczby rzędów ukrywa nadmiarowe pozycje bez kasowania ich historii; ponowne zwiększenie przywraca wcześniejsze statusy, notatki i zdjęcia.

Widok „Zapotrzebowanie” przedstawia wyłącznie ilości wymagane przez projekt. Przełącznik „Cała farma / strefa” pozwala porównać ogólny BOM z zapotrzebowaniem wybranej strefy. Obliczenia nie korzystają ze stanów magazynowych ani fizycznych dostaw WZ.

Osobna zakładka „Dostawy na budowę” prowadzi fizyczny rejestr WZ dla pełnego katalogu BOM ESET oraz modułu Jinko. Stan każdej pozycji zaczyna się od zera. Użytkownik może dodać wielopozycyjny dokument WZ, podać ilości dostarczone i uszkodzone, a system pokazuje zestawienie „dostarczone / na polu / wymagane / bilans”. Dostawy nie zmieniają zapotrzebowania projektowego.

## Zatwierdzona baza źródłowa

Program bazuje na dziesięciu dokumentach w folderze `project_sources`:

1. `łaczenia rur.pdf` — rysunki słupów QZ1–QZ4, FZ1–FZ2 i NZ1;
2. `planimetria.pdf` — rysunki wariantów 1PX28/42/56/70 i tabele BOM;
3. `planimetria - warianty i BOM.pdf` — dostarczona osobno 12-stronicowa wersja rysunków i tabel BOM;
4. `planimetria 6,5mw.pdf` — planimetria RF-GIULIETTA, Momo, 6,4915 MWp;
5. `montaż mechaniczny.pdf` — instrukcje, narzędzia, momenty oraz tabele rur i płatwi;
6. `manual v.2.pdf` — pełny manual producenta ESET Solar;
7. `montaż mechaniczny 3.pdf` — katalog głównych komponentów ESET;
8. `montaż mechaniczny 4.pdf` — katalog rur, płatwi i zestawów M12–M18;
9. `montaż mechaniczny 5.pdf` — typy rur i słupów trackera.
10. `JKM710-735N-66HL5-BDV-Z3-EN.pdf` — karta modułu Jinko 710–735 W, 132 ogniwa, 2384×1303×33 mm i 37,5 kg.

[source-manifest.json](project_sources/source-manifest.json) przechowuje sumy SHA-256, zakres i dane źródłowe. [eset-bom.json](project_sources/eset-bom.json) zawiera znormalizowane relacje wariant–komponent i ilości z tabel BOM. Inny wgrany plik pozostaje dokumentem pomocniczym i nie zmienia zapotrzebowania ani instrukcji.

Zapotrzebowanie obejmuje komponenty systemowe, w tym słupy, TCU i odbiornik. Liczba i parametry modułów Jinko są prezentowane osobno i nie zmieniają mechanicznego BOM ESET. Zakres prac montażowych nadal wyłącza operację wbijania słupów, montaż modułów PV, okablowanie, uziemienie i uruchomienie elektryczne.

## Pozostałe funkcje

- projekty można dodawać, edytować, archiwizować, przywracać i usuwać;
- meldunek zawiera liczbę zbudowanych rzędów, liczbę osób, godziny, dowolny opis prac, notatki i dziennik QA/QC;
- zdjęcia można dodawać bezpośrednio z aparatu telefonu i przeglądać w historii meldunku;
- moduł RFI rejestruje problem, priorytet, opis i zdjęcie;
- zakładka „Mapa / Planimetria” wyświetla zatwierdzone plany źródłowe oraz plany PDF wgrywane przez kierownika, z powiększaniem, pobieraniem i wygodnym podglądem na telefonie;
- raport dzienny PDF zawiera prace, KPI i dziennik QA/QC;
- WebSocket synchronizuje urządzenia, a PWA buforuje odczyty i kolejkuje zapisy offline;
- każdy rząd ma zakładkę „Specyfikacja i BOM” z wartościami źródłowymi i ręcznymi korektami kierownika, wyraźnie oznaczonymi jako nadpisane;
- pliki pomocnicze mają status zapisany / przeanalizowany / zatwierdzony do obliczeń;
- interfejs działa po polsku na telefonie, tablecie i komputerze.

## Konta startowe i bezpieczeństwo

| Rola | Login | Hasło w instalacji lokalnej (SQLite) |
|---|---|---|
| Kierownik budowy | `kierownik` | `Asolar2026!` |
| Brygadzista 1 | `brygadzista1` | `Brygada1-2026!` |
| Brygadzista 2 | `brygadzista2` | `Brygada2-2026!` |

- Hasła domyślne działają **wyłącznie** w samodzielnej instalacji lokalnej i należy je zmienić po pierwszym logowaniu (Użytkownicy → Zmień hasło).
- Na serwerze (PostgreSQL albo `ASOLAR_REQUIRE_PASSWORDS=1`) aplikacja **nie uruchomi się** bez `ASOLAR_SECRET` i bez haseł `ASOLAR_MANAGER_PASSWORD`, `ASOLAR_FOREMAN1_PASSWORD`, `ASOLAR_FOREMAN2_PASSWORD` potrzebnych do utworzenia brakujących kont.
- Hasła są odczytywane tylko przy **tworzeniu** brakującego konta. Restart serwera nie resetuje haseł istniejących użytkowników.
- Hasła są przechowywane jako skróty PBKDF2-SHA256 (240 000 iteracji). Frontend nie zawiera żadnych haseł.
- Uprawnienia są sprawdzane w backendzie: odbiór QA/QC, zarządzanie użytkownikami, wgrywanie i usuwanie planimetrii, korekty materiałowe rzędu, zmiana statusu RFI oraz usuwanie danych są zastrzeżone dla kierownika. Brygadzista edytuje tylko własne meldunki.
- Kierownik może dodawać konta, zmieniać hasła oraz dezaktywować konta (bez możliwości odebrania uprawnień samemu sobie).

## Wdrożenie na Render przez Blueprint

Repozytorium zawiera [render.yaml](render.yaml), obraz Docker (Python 3.11) i konfigurację PostgreSQL.

Najszybciej: kliknij przycisk **„Deploy to Render”** na górze tego pliku (lub otwórz `https://render.com/deploy?repo=https://github.com/lukaa23/5mw-logistyka-`), zaloguj się w Render i przejdź od kroku 4.

Każda zmiana w repozytorium jest sprawdzana przez CI ([.github/workflows/ci.yml](.github/workflows/ci.yml)): testy backendu na PostgreSQL 16, testy frontendu oraz zbudowanie obrazu Docker i test dymny ([scripts/smoke_test.py](scripts/smoke_test.py)) — kierownik i brygadziści, powiadomienia WebSocket, zdjęcia z `client_id`, restart kontenera bez utraty danych i haseł.

1. Wypchnij gałąź do GitHuba (wdrożenie produkcyjne wykonuj świadomie — `autoDeploy` w Blueprincie wdraża każdą zmianę wybranej gałęzi).
2. W Render wybierz **New + → Blueprint** i połącz repozytorium.
3. Render utworzy usługę `asolar-eset-tracker` i bazę `asolar-postgres`; `DATABASE_URL` i `ASOLAR_SECRET` zostaną ustawione automatycznie.
4. W formularzu wpisz silne hasła `ASOLAR_MANAGER_PASSWORD`, `ASOLAR_FOREMAN1_PASSWORD` i `ASOLAR_FOREMAN2_PASSWORD`.
5. Po statusie **Live** otwórz `https://…onrender.com/api/health` — powinno pokazać `"database": "postgresql"`, `"file_storage": "database"`, `"realtime": "websocket"`, `"version": "4.5.1"`.
6. Przekaż **jeden adres HTTPS** obu brygadzistom. Wszystkie urządzenia pracują na tym samym serwerze i tej samej bazie.

Adresy `postgres://…` i `postgresql://…` są automatycznie przekształcane na sterownik psycopg 3.

### Trwałość danych i ograniczenia hostingu

- Dane, zdjęcia i dokumenty wgrywane przez użytkowników są zapisywane w bazie danych (BLOB), więc restart kontenera ich nie usuwa — pod warunkiem, że baza jest trwała.
- Starsze pliki z katalogu `data/uploads` są nadal odczytywane.
- **Darmowe plany hostingu nie gwarantują bezterminowego przechowywania.** Darmowa usługa WWW może usypiać się po bezczynności (pierwsze otwarcie trwa dłużej), a darmowa baza PostgreSQL w Render ma ograniczony czas życia i pojemność według aktualnego cennika. Do pracy produkcyjnej wybierz płatny plan bazy z kopiami zapasowymi i sprawdź bieżące warunki u dostawcy.
- Zdjęcia w bazie zwiększają jej rozmiar (limit 25 MB na zdjęcie, 100 MB na dokument — `ASOLAR_MAX_DOCUMENT_MB`). Monitoruj zajętość bazy.

### Kopie zapasowe

```bash
# PostgreSQL (pełna kopia, łącznie ze zdjęciami i dokumentami)
pg_dump "$DATABASE_URL" --format=custom --file=asolar-$(date +%F).dump
# odtworzenie
pg_restore --clean --no-owner --dbname "$DATABASE_URL" asolar-2026-10-17.dump
```

Instalacja lokalna: zatrzymaj program i skopiuj cały folder `data/` (`data/asolar.db` oraz `data/uploads`).

### Konfiguracja własnego PostgreSQL

```bash
DATABASE_URL=postgresql://asolar:haslo@serwer:5432/asolar
ASOLAR_SECRET=dlugi-losowy-klucz
ASOLAR_MANAGER_PASSWORD=...  ASOLAR_FOREMAN1_PASSWORD=...  ASOLAR_FOREMAN2_PASSWORD=...
python server.py
```

Schemat jest tworzony i uzupełniany automatycznie przy starcie (brakujące kolumny są dodawane, istniejące dane pozostają nienaruszone).

## Instalacja PWA na telefonie

- **Android / Chrome:** otwórz adres HTTPS → menu ⋮ → *Zainstaluj aplikację* / *Dodaj do ekranu głównego*.
- **iPhone / Safari:** przycisk *Udostępnij* → *Do ekranu początkowego*.
- PWA buforuje tylko powłokę aplikacji (HTML, skrypty, ikony). Dane zawsze pochodzą z serwera; ostatnio pobrane widoki są pamiętane lokalnie na wypadek braku zasięgu.

### Praca bez zasięgu (telefon brygadzisty)

- **Wszystkie zmiany w terenie działają bez internetu:** statusy „Zbudowane” / „Sprawdzone QC/QA”, notatki, **zdjęcia z aparatu**, meldunki (także ze zdjęciami), RFI, dostawy WZ, konfiguracja stref i kolejność rzędów.
- Zmiany trafiają do trwałej kolejki w **IndexedDB** telefonu (zdjęcia jako pliki binarne). Gdy IndexedDB jest niedostępne, zapisy tekstowe trafiają do localStorage, a o zdjęciach aplikacja informuje komunikatem.
- Po odzyskaniu połączenia kolejka jest wysyłana automatycznie (zdarzenie „online”, start aplikacji i co 15 s), w kolejności zapisu. Każdy wpis ma `client_id`, więc ponowne wysłanie — np. po zerwaniu połączenia w trakcie wysyłania zdjęcia — nie tworzy duplikatu.
- Na serwerze zapisuje się **czas zmiany z telefonu** (np. kiedy rząd zbudowano bez zasięgu), a nie czas synchronizacji. Czas z przyszłości lub starszy niż 30 dni jest zastępowany czasem serwera.
- Zdjęcie do meldunku lub RFI utworzonego offline jest dołączane po jego `client_id` (`/api/{worklog|rfi}/by-client/{client_id}/photos`).
- Niewysłane zmiany są widoczne od razu: status rzędu, liczniki notatek i zdjęć oraz miniatury „czeka na wysłanie”.
- Wpis odrzucony przez serwer (np. odbiór QC rzędu, który ktoś cofnął) **nie jest usuwany** — jest oznaczony w panelu synchronizacji, można go ponowić albo zapisać w kopii.
- Konflikty: przy równoczesnej zmianie tego samego rzędu przez dwie osoby obowiązuje zmiana wysłana jako ostatnia; każda zmiana zostaje w dzienniku zdarzeń (`audit_events`).
- Po zalogowaniu aplikacja zapamiętuje konto, więc uruchomienie telefonu bez zasięgu nie wylogowuje użytkownika (dane widoków pochodzą z ostatniej kopii).
- **Wskaźnik w górnym pasku** (*Na żywo / Łączenie… / Offline*, liczba zmian w kolejce, liczba odrzuconych) otwiera **panel synchronizacji**: lista zmian, „Wyślij teraz”, „Ponów odrzucone”, „Pobierz kopię niewysłanych zmian”, „Przywróć dane z kopii”, a dla kierownika — „Pobierz kopię bazy (SQLite)”.

Wymagania i ograniczenia:

- Aby PWA działała offline (także po ponownym otwarciu bez zasięgu), telefon musi **raz otworzyć aplikację online pod adresem HTTPS** — wtedy service worker zapisuje powłokę i skrypty. Przeglądarki nie instalują service workera pod adresem `http://` innym niż `localhost`.
- Dokumenty techniczne i planimetrie wgrywa się wyłącznie online.
- Pojemność pamięci telefonu dla zdjęć zależy od przeglądarki; przy dużej liczbie zdjęć offline warto zsynchronizować je, gdy pojawi się zasięg.

### Ekran ratunkowy zamiast „białego ekranu”

- Każdy widok i cała aplikacja są osłonięte przez Error Boundary. Błąd pokazuje komunikat z przyciskami **„Odśwież aplikację”**, „Spróbuj ponownie” oraz **„Pobierz kopię niewysłanych zmian” / „Przywróć dane z kopii”** (plik JSON z notatkami, statusami i zdjęciami).
- `window.onerror` i `unhandledrejection` są przechwytywane globalnie: błąd trafia do dziennika (ostatnie 20 w localStorage) i komunikatu, aplikacja działa dalej.
- Moduł Planimetrii jest ładowany na żądanie z jedną ponowną próbą; błąd wczytania (brak sieci) kończy się ekranem ratunkowym.
- Jeżeli nie wczyta się nawet główny skrypt, `index.html` sam pokazuje prosty ekran z przyciskami „Odśwież aplikację” i „Wyczyść pamięć podręczną i odśwież” (czyści tylko pliki aplikacji, nie kolejkę zmian).

**Procedura ręczna** (uzupełnia testy automatyczne): w Chrome DevTools → *Network* ustaw **Offline**, zmień status rzędu, dodaj notatkę i zdjęcie, odśwież stronę (dane i zmiany pozostają, brak białego ekranu), przywróć **Online** i sprawdź, że licznik kolejki spada do zera, a zmiany widać na drugim urządzeniu. W trakcie wysyłania zdjęcia przełącz na Offline — zdjęcie musi pojawić się w kolejce, nie zniknąć.

## Aplikacja desktopowa (Electron) — komputer kierownika

Folder [desktop](desktop) zawiera aplikację Electron z ikoną ASOLAR (`desktop/build/icon.ico`) i konfiguracją `electron-builder`.

- **Tryb serwera (domyślny):** aplikacja uruchamia lokalny serwer ASOLAR (FastAPI + SQLite) i otwiera go w oknie. Baza, zdjęcia i dokumenty są zapisywane w profilu użytkownika: `%APPDATA%\ASOLAR ESET Tracker Manager\data` — nie znikają przy braku internetu ani przy aktualizacji programu. Klucz sesji jest generowany przy pierwszym uruchomieniu (`secret.key`).
- **Udostępnianie telefonom:** menu *Serwer → Udostępnij serwer telefonom w sieci lokalnej*, potem *Pokaż adresy dla telefonów*. Telefony w tej samej sieci Wi-Fi otwierają `http://ADRES-KOMPUTERA:8765` (zapora Windows może zapytać o zgodę). Do pełnej PWA offline potrzebny jest adres HTTPS — np. wspólny serwer w Render albo tunel HTTPS do komputera kierownika.
- **Tryb klienta:** *Serwer → Połącz z serwerem zdalnym* (pole `serverUrl` w `config.json`) albo plik `server-url.txt` obok programu — aplikacja otwiera wtedy wspólny serwer i nie potrzebuje Pythona.
- Zajęty port 8765 jest wykrywany — program pokazuje komunikat zamiast otwierać starą instancję. Druga kopia programu nie startuje (przełącza na otwarte okno).
- Kopia bazy: panel synchronizacji → „Pobierz kopię bazy (SQLite)” albo *Plik → Otwórz folder danych*.
- **Wymaganie trybu serwera:** Python 3.11 z Python Launcher (`py -3.11`). Przy pierwszym uruchomieniu program jednorazowo instaluje składniki serwera do profilu użytkownika (wymaga Internetu, ok. 1 minuty). Python nie jest wbudowany w instalator.

Budowanie (Windows, Node.js 20+):

```bash
cd frontend && npm ci && npm run build && cd ..
cd desktop && npm ci && npm test && npx electron-builder --win nsis portable
```

Wynik w `desktop/dist`: `ASOLAR-<wersja>-instalator.exe` (instalator NSIS ze skrótami na pulpicie i w menu Start) oraz `ASOLAR-<wersja>-portable.exe`. Pliki **nie są podpisane cyfrowo** — Windows SmartScreen pokaże ostrzeżenie „Nieznany wydawca” do czasu podpisania certyfikatem firmy (zmienne `CSC_LINK` / `CSC_KEY_PASSWORD` w electron-builder). Ikony (`.ico`, PNG dla PWA) generuje `py -3.11 windows/build_icon.py` (wymaga Pillow).

## Uruchomienie na Windows (Python 3.11)

- `Uruchom-Windows.bat` zawsze używa `py -3.11`, działa względem własnego katalogu, przy pierwszym uruchomieniu instaluje zależności do `runtime-packages` i pokazuje zrozumiałe komunikaty błędów.
- `ASOLAR.exe` (źródło: [windows/asolar-launcher.c](windows/asolar-launcher.c)):
  - jeśli obok leży `server-url.txt`, otwiera wspólny adres serwera — bez lokalnego Pythona;
  - w przeciwnym razie sprawdza, czy port 8765 jest wolny (zajęty port = komunikat zamiast otwierania starej instancji), a potem uruchamia lokalny backend przez `py -3.11`.

### Budowanie ASOLAR.exe

Windows (MSYS2 / MinGW-w64 w `PATH`, Pillow do ikony: `py -3.11 -m pip install pillow`):

```powershell
powershell -ExecutionPolicy Bypass -File windows\build_launcher.ps1
```

Linux (kompilacja krzyżowa): `bash windows/build_launcher.sh`.

### Paczka klienta do wspólnego serwera

```powershell
Copy-Item server-url.txt.example server-url.txt   # wpisz adres HTTPS z Render
Compress-Archive -Path ASOLAR.exe,server-url.txt,README.md -DestinationPath ASOLAR-Klient-PC.zip -Force
```

Pełna paczka lokalna zawiera dodatkowo `app`, `frontend/dist`, `project_sources`, `requirements.txt`, `desktop.py`, `server.py` i `Uruchom-Windows.bat` (bez `server-url.txt`).

## Uruchomienie deweloperskie

Wymagane: Python 3.11 i Node.js 20+.

```bash
py -3.11 -m venv .venv
.venv/Scripts/python -m pip install -r requirements-dev.txt   # Linux/macOS: .venv/bin/python
cd frontend && npm ci && npm run build && cd ..
.venv/Scripts/python server.py
```

Interfejs: `http://127.0.0.1:8765`, dokumentacja API: `/docs`. Tryb deweloperski frontendu z proxy: `cd frontend && npm run dev`.

## Docker

```bash
ASOLAR_SECRET="dlugi-losowy-klucz" docker compose up --build
```

Domyślnie SQLite w wolumenie `asolar_data`. Po ustawieniu `DATABASE_URL=postgresql://…` aplikacja korzysta z PostgreSQL.

## Testy

```bash
.venv/Scripts/python -m pytest -q          # backend
cd frontend && npm test                    # React, service worker, odporność offline
cd frontend && npm run build               # build produkcyjny Vite
cd desktop && npm test                     # funkcje aplikacji Electron
```

- **Backend** (`tests/test_api.py`, `tests/test_regression.py`): role i logowanie, brak resetu haseł po restarcie, wymagane zmienne serwera, trwałe notatki i zdjęcia w bazie, historia przy zmniejszaniu i zwiększaniu liczby rzędów, ręczne sortowanie z trwałym ID, warianty łączone jako suma BOM, korekty materiałowe rzędu, zapotrzebowanie niezależne od dostaw, zerowy stan dostaw i deduplikacja WZ, planimetria i uprawnienia, analiza plików pomocniczych bez zmiany bazy technicznej, KPI i prognoza, raport PDF, zdarzenia WebSocket, 404 dla brakujących skryptów, zgodność manifestu SHA-256 dziesięciu źródeł.
- **Frontend** (`frontend/tests`): Planimetria (odświeżanie synchronizacji, usunięcie bieżącego planu, zmiana projektu, spóźnione odpowiedzi, zmiana planu w trakcie pobierania, brak starego PDF pod nowym tytułem, zwalnianie blob URL, null/pusta lista/niepoprawne rekordy, brak tytułu, błędna data, błąd pobierania), service worker (schematy rozszerzeń, obcy origin, API, WebSocket, POST, Range, błąd `cache.put`/`caches.open`, brak cache dla 500/206, fallback tylko dla nawigacji, usuwanie wyłącznie starych cache ASOLAR), logowanie bez haseł w kodzie, ErrorBoundary i kolejka offline.

## Zmiany w wersji 4.6.1

- Dostawy WZ: naprawiono znikanie danych w formularzu przy odświeżaniu w tle; wyszukiwarka elementów BOM (nazwa, kod, specyfikacja, bez polskich znaków, tolerancja literówki); edycja i usuwanie WZ przez kierownika z potwierdzeniem i przeliczeniem bilansu; szkic WZ zachowywany do zapisu.
- Wybór strefy w „Zapotrzebowaniu” nie resetuje się już przy synchronizacji.

## Zmiany w wersji 4.6.0

- Aplikacja desktopowa Electron (instalator i wersja portable `.exe` z ikoną ASOLAR): serwer kierownika z bazą w profilu użytkownika, udostępnianie w sieci lokalnej, tryb klienta.
- Pełna praca offline na telefonie: kolejka w IndexedDB obejmuje zdjęcia; deduplikacja zdjęć po `client_id`; czas zmiany z telefonu; zdjęcia do meldunków/RFI utworzonych offline; panel synchronizacji; start bez zasięgu bez wylogowania.
- Ekran ratunkowy (odświeżenie, kopia i przywrócenie niewysłanych zmian), globalne łapanie błędów, zabezpieczenie `index.html`, ładowanie modułów z ponowieniem; service worker zapisuje skrypty już przy pierwszej wizycie.
- Kopia zapasowa bazy SQLite dla kierownika (`/api/admin/backup`), `manifest.json` z ikonami PNG dla Androida/iOS.
- Testy odporności: brak sieci, zerwanie połączenia podczas wysyłania zdjęć, odrzucenie przez serwer, błędy wczytania modułów, błędy globalne.

## Zmiany w wersji 4.5.1

- **Planimetria — poprawka białego ekranu** (`TypeError: Cannot read properties of undefined (reading 'title')`): synchronizacja nie zeruje już wyboru; PDF jest renderowany tylko, gdy istnieje zarówno dokument, jak i odpowiadający mu adres (klucz projekt + dokument + `file_url`); spóźnione odpowiedzi są ignorowane; adresy blob są zwalniane; błędy pokazują komunikat. Widoki są dodatkowo osłonięte przez ErrorBoundary.
- **Service worker** obsługuje wyłącznie GET http/https do własnego origin, pomija API/WebSocket/POST/Range i rozszerzenia przeglądarki, nie buforuje błędów ani odpowiedzi częściowych, a awaria Cache API nie blokuje odpowiedzi sieciowej. Serwer zwraca 404 dla brakujących plików statycznych zamiast `index.html`.
- Korekty materiałowe pojedynczego rzędu z rozróżnieniem wartości źródłowych i nadpisanych, doliczane do zapotrzebowania jako różnica.
- Statusy plików: *zapisany / przeanalizowany / zatwierdzony do obliczeń*; rzeczywista analiza PDF, XLSX i DXF ASCII; DWG jest tylko zapisywany (brak parsera).
- RFI z osobą odpowiedzialną i wieloma zdjęciami; meldunki z autorem i wieloma zdjęciami; KPI z jawnymi założeniami prognozy; rozszerzony raport dzienny PDF z polskimi znakami.
- Kontrolowane usuwanie projektu (najpierw archiwizacja, potwierdzenie nazwą), zarządzanie kontami, wymagane zmienne środowiskowe na serwerze, Docker na Pythonie 3.11, przypięte wersje zależności frontendu.
