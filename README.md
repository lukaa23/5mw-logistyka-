# ASOLAR ESET Tracker Manager

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
- interfejs działa po polsku na telefonie, tablecie i komputerze.

## Uruchomienie na Windows

### Klient do wspólnego serwera

1. Pobierz i rozpakuj pełną paczkę ZIP.
2. Skopiuj `server-url.txt.example` jako `server-url.txt`.
3. Wpisz w nim jedną linię z adresem wdrożenia, np. `https://asolar-eset-tracker.onrender.com`.
4. Uruchom `ASOLAR.exe`. W tym trybie program otwiera wspólny serwer i nie wymaga lokalnego Pythona.

### Samodzielny serwer lokalny

1. Zainstaluj Python 3.11 razem z programem Python Launcher (`py`).
2. Usuń `server-url.txt`, jeśli istnieje.
3. Uruchom `ASOLAR.exe` albo awaryjnie `Uruchom-Windows.bat`.

W trybie lokalnym `ASOLAR.exe` używa polecenia `py -3.11`, instaluje zależności do `runtime-packages` i przechowuje bazę w `data/asolar.db`.

## Konta startowe

| Rola | Login | Hasło |
|---|---|---|
| Kierownik Budowy | `kierownik` | `Asolar2026!` |
| Brygadzista 1 | `brygadzista1` | `Brygada1-2026!` |
| Brygadzista 2 | `brygadzista2` | `Brygada2-2026!` |

Hasła w tabeli dotyczą instalacji lokalnej. Wdrożenie Render wymaga wpisania własnych haseł. Kierownik może później tworzyć kolejne konta.

## Wdrożenie na Render — krok po kroku

Repozytorium zawiera gotowy [render.yaml](render.yaml), obraz Docker i konfigurację PostgreSQL.

1. Umieść repozytorium na GitHubie.
2. Zaloguj się w Render, wybierz **New + → Blueprint** i połącz repozytorium.
3. Render odczyta `render.yaml` i utworzy usługę `asolar-eset-tracker` oraz bazę `asolar-postgres`.
4. W formularzu wpisz silne wartości dla `ASOLAR_MANAGER_PASSWORD`, `ASOLAR_FOREMAN1_PASSWORD` i `ASOLAR_FOREMAN2_PASSWORD`.
5. Wybierz **Apply** i poczekaj, aż wdrożenie otrzyma status **Live**.
6. Otwórz adres z Render. Kontrolny adres `/api/health` powinien pokazać `database: postgresql`, `file_storage: database` i `realtime: websocket`.
7. Przekaż ten sam link obu brygadzistom. Na telefonie mogą wybrać „Dodaj do ekranu głównego”, aby zainstalować PWA.

Darmowa usługa może usypiać aplikację po bezczynności, dlatego pierwsze otwarcie może potrwać kilkadziesiąt sekund. Dane pozostają w PostgreSQL. Dla stałej pracy produkcyjnej należy wybrać plan bazy bez terminu wygaśnięcia zgodnie z aktualną ofertą hostingu.

Najważniejsze zmienne serwera:

| Zmienna | Zastosowanie |
|---|---|
| `DATABASE_URL` | Wspólna baza PostgreSQL; Blueprint ustawia ją automatycznie |
| `ASOLAR_SECRET` | Podpisywanie sesji; Render generuje wartość automatycznie |
| `ASOLAR_MANAGER_PASSWORD` | Hasło konta `kierownik` przy tworzeniu bazy |
| `ASOLAR_FOREMAN1_PASSWORD` | Hasło konta `brygadzista1` |
| `ASOLAR_FOREMAN2_PASSWORD` | Hasło konta `brygadzista2` |

## Pakowanie programu na PC

Po przebudowaniu frontendu i launchera można utworzyć paczkę w PowerShell:

```powershell
Copy-Item server-url.txt.example server-url.txt
# Zmień adres w server-url.txt na adres z Render.
Compress-Archive -Path ASOLAR.exe,server-url.txt,README.md -DestinationPath ASOLAR-Cloud-PC.zip -Force
```

Taka paczka jest lekkim klientem do wspólnego serwera. Pełna paczka lokalna powinna dodatkowo zawierać `app`, `frontend/dist`, `project_sources`, `requirements.txt`, `desktop.py`, `server.py` i `Uruchom-Windows.bat`. Źródła launchera i polecenie budowania znajdują się w `windows/build_launcher.sh`.

## Uruchomienie deweloperskie

Wymagane są Python 3.11+ i Node.js 20+.

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
cd frontend
npm ci
npm run build
cd ..
.venv/bin/python server.py
```

Dokumentacja OpenAPI jest dostępna pod `/docs`.

## Docker

```bash
ASOLAR_SECRET="długi-losowy-klucz" docker compose up --build
```

Domyślną bazą jest SQLite. Po ustawieniu `DATABASE_URL=postgresql://...` aplikacja automatycznie korzysta z PostgreSQL przez sterownik psycopg 3.

## Testy

```bash
.venv/bin/python -m unittest -v tests/test_api.py
cd frontend && npm run build
```

Testy sprawdzają strefy, zapotrzebowanie ogólne i strefowe, zerowy stan i sumowanie pełnych dostaw BOM, niezależność dostaw od obliczeń projektowych, automatyczną numerację i ręczne sortowanie rzędów, trwałą historię notatek i wielu zdjęć, autora ostatniej zmiany, siedem wariantów, sumowanie BOM-ów łączonych, momenty dokręcania, role, meldunki, QA/QC, podgląd planimetrii PDF, raport PDF oraz integralność dziesięciu dokumentów źródłowych.
