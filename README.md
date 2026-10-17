# ASOLAR ESET Tracker Manager

Responsywna aplikacja PWA do konfiguracji trackerów ESET, wyliczania zapotrzebowania projektowego, prowadzenia meldunków brygadzisty i kontroli QA/QC na farmie PV.

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

Widok operacyjny pozwala oznaczać każdy wygenerowany rząd jako zbudowany i odebrany QA/QC, prowadzić indywidualne notatki, robić zdjęcia bezpośrednio aparatem telefonu oraz ustawiać rzeczywistą kolejność rzędów przyciskami Góra/Dół. Kolejność jest zapisywana w bazie i synchronizowana między urządzeniami. Zmniejszenie liczby rzędów ukrywa nadmiarowe pozycje bez kasowania ich historii; ponowne zwiększenie przywraca wcześniejsze statusy, notatki i zdjęcia.

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
- raport dzienny PDF zawiera prace, KPI i dziennik QA/QC;
- WebSocket synchronizuje urządzenia (wskaźnik „Na żywo / Łączenie / Offline”, ponowne łączenie i odświeżanie co 15 s), a kolejka lokalna przechowuje proste zapisy podczas utraty sieci;
- zakładka **Planimetria** wyświetla zatwierdzone plany PDF w aplikacji (przybliżanie, dopasowanie, pobieranie); kierownik wgrywa oficjalne plany i usuwa wyłącznie plany dodatkowe — zatwierdzone źródła są chronione;
- interfejs działa po polsku na telefonie, tablecie i komputerze.

## Uruchomienie na Windows

1. Pobierz i rozpakuj pełną paczkę ZIP.
2. Zainstaluj Python 3.11 razem z programem Python Launcher (`py`).
3. Uruchom `Uruchom-Windows.bat`.

Skrypt używa polecenia `py -3.11`. Przy pierwszym uruchomieniu instaluje zależności w lokalnym folderze `runtime-packages`, a następnie otwiera aplikację. Dane i zdjęcia są przechowywane w folderze `data`.

## Konta i hasła

Trzy konta startowe powstają przy pierwszym uruchomieniu, jeśli jeszcze nie istnieją:

| Login | Rola | Zmienna z hasłem |
|---|---|---|
| `kierownik` | kierownik | `ASOLAR_MANAGER_PASSWORD` |
| `brygadzista1` | brygadzista | `ASOLAR_FOREMAN1_PASSWORD` |
| `brygadzista2` | brygadzista | `ASOLAR_FOREMAN2_PASSWORD` |

- Hasła mają minimum 8 znaków i są przechowywane jako skróty PBKDF2. W kodzie ani we froncie nie ma haseł.
- Restart **nie zmienia** haseł istniejących użytkowników. Zmiana zmiennej środowiskowej dotyczy tylko kont, które dopiero powstają.
- Jeżeli zmiennej brakuje (np. lokalna instalacja), hasło jest losowane i zapisywane w pliku `data/initial-passwords.txt`; po pierwszym zalogowaniu usuń ten plik.
- Instalacje z wcześniejszych wersji zachowują swoje konta (`brygadzista`, `magazynier`); `brygadzista1` i `brygadzista2` są dodawane obok nich.
- Kierownik tworzy dodatkowe konta w zakładce Użytkownicy. Uprawnienia są sprawdzane w backendzie: odbiór QA/QC, użytkownicy i wgrywanie planów należą do kierownika; brygadzista zgłasza montaż, notatki, zdjęcia, meldunki i dostawy.
- W instalacji dostępnej w sieci ustaw własny, długi `ASOLAR_SECRET`.

## Uruchomienie lokalne

Wymagane są Python 3.11+ i Node.js 22+ (do budowy interfejsu).

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
cd frontend && npm ci && npm run build && cd ..
ASOLAR_MANAGER_PASSWORD='...' ASOLAR_FOREMAN1_PASSWORD='...' ASOLAR_FOREMAN2_PASSWORD='...' .venv/bin/python server.py
```

Dokumentacja OpenAPI jest dostępna pod `/docs`. Na Windows użyj `Uruchom-Windows.bat` (zawsze `py -3.11`, bez stałych ścieżek).

> Katalog `frontend/dist` w repozytorium jest wynikiem ostatniego pełnego buildu. Po zmianach w `frontend/src` trzeba go odtworzyć poleceniem `npm run build` (Docker i Render robią to automatycznie).

## Laptop jako serwer + telefony z Androidem (bez Render i bez Google Play)

Zdjęcia, notatki i cała baza zapisują się wtedy w folderze `data` na laptopie (`data/asolar.db`).

1. Uruchom **`Uruchom-Windows-Siec.bat`** (zamiast zwykłego). Przy pierwszym starcie Zapora Windows zapyta o dostęp — zezwól w sieciach **prywatnych**.
2. W czarnym oknie pojawi się adres dla telefonów, np. `http://192.168.0.15:8765`. Kierownik zobaczy go też w aplikacji: Użytkownicy → „Adres dla telefonów”.
3. Telefon musi być w **tej samej sieci Wi-Fi** (router na budowie albo hotspot z telefonu). Laptop musi być włączony i nie może usypiać.
4. Zalecany jest stały adres laptopa (rezerwacja DHCP w routerze), żeby nie zmieniał się między dniami.

Połączenie w sieci lokalnej to zwykłe HTTP, bez szyfrowania — używaj prywatnej sieci, nie publicznej. Bez HTTPS przeglądarka nie zainstaluje PWA, dlatego na telefony jest osobna aplikacja Android.

**Kopia zapasowa:** zatrzymaj program i skopiuj folder `data` (albo sam plik `data/asolar.db`) na dysk zewnętrzny lub do chmury.

### Aplikacja Android (APK)

Folder `android-app` to cienka otoczka (Capacitor): przy pierwszym uruchomieniu pytasz o adres laptopa, aplikacja go zapamiętuje i ładuje interfejs z laptopa — zmiany w aplikacji nie wymagają nowego APK.

1. Na GitHubie: **Actions → „Android APK” → Run workflow**.
2. Po zakończeniu pobierz artefakt `asolar-debug-apk` (plik `app-debug.apk`).
3. Na telefonie włącz „Instaluj nieznane aplikacje” dla przeglądarki/menedżera plików i zainstaluj plik.
4. Wpisz adres laptopa (wystarczy `192.168.0.15`, port 8765 jest domyślny). Aby zmienić adres później, odinstaluj i zainstaluj aplikację albo wyczyść jej dane.

Workflow i konfiguracja Android nie zostały jeszcze uruchomione — pierwszy przebieg może wymagać poprawek. Wersje Capacitora są ustawione na `latest`; po pierwszym udanym buildzie warto je przypiąć.

## PostgreSQL i trwałość danych

Ustaw `DATABASE_URL`. Adresy `postgres://` i `postgresql://` są zamieniane na `postgresql+psycopg://` (psycopg 3). Brakujące kolumny są dodawane automatycznie, bez kasowania danych.

Zdjęcia i nowe dokumenty (w tym plany PDF) zapisują się **w bazie** jako dane binarne wraz z metadanymi, więc kopia zapasowa bazy obejmuje także pliki, a restart serwera niczego nie resetuje. Starsze pliki z katalogu `data/uploads` nadal są odczytywane. Dokumenty źródłowe z `project_sources` są kopiowane do `data/uploads` przy starcie.

Kopie zapasowe: dla PostgreSQL `pg_dump "$DATABASE_URL" > kopia.sql`; dla SQLite skopiuj plik `data/asolar.db` przy zatrzymanym serwerze.

## Docker

```bash
export ASOLAR_SECRET='długi-losowy-klucz' ASOLAR_MANAGER_PASSWORD='...' ASOLAR_FOREMAN1_PASSWORD='...' ASOLAR_FOREMAN2_PASSWORD='...'
docker compose up --build                       # SQLite w wolumenie
POSTGRES_PASSWORD='...' DATABASE_URL='postgresql://asolar:...@db:5432/asolar' docker compose --profile postgres up --build
```

Obraz buduje interfejs, uruchamia testy frontendu (`npm test`) i dołącza `project_sources` z bazą BOM.

## Wdrożenie na Render

1. W Render wybierz **New → Blueprint** i wskaż to repozytorium (`render.yaml`).
2. Uzupełnij `ASOLAR_MANAGER_PASSWORD`, `ASOLAR_FOREMAN1_PASSWORD` i `ASOLAR_FOREMAN2_PASSWORD`.
3. Przekaż brygadzistom jeden adres HTTPS usługi.

Nazwy i ceny planów Render zmieniają się; plik `render.yaml` zawiera plany płatne, bo trwałe przechowywanie danych wymaga trwałej bazy PostgreSQL. Darmowe instancje i bazy mogą wygasać — sprawdź aktualne warunki przed wdrożeniem. Wdrożenie nie jest wykonywane automatycznie.

## Instalacja PWA

Otwórz adres HTTPS w Chrome lub Safari i wybierz „Zainstaluj aplikację” / „Dodaj do ekranu głównego”. Service worker obsługuje wyłącznie GET do własnego origin; API, WebSocket, żądania Range i rozszerzenia przeglądarki są pomijane. Wgrywanie zdjęć i plików wymaga połączenia z serwerem — kolejka offline obejmuje tylko proste zapisy.

## Testy

```bash
cd frontend && npm test                          # service worker i logika Planimetrii (Node 22, bez instalacji pakietów)
python -m unittest tests/test_standalone.py      # adres bazy, hasła, integralność źródeł (bez FastAPI)
.venv/bin/python -m unittest -v tests/test_api.py  # pełny backend (wymaga requirements.txt)
cd frontend && npm run build
```

Testy sprawdzają m.in.: konta i role, hasła z zmiennych środowiskowych, plany PDF i uprawnienia, ochronę zatwierdzonych źródeł, zdjęcia w bazie, strefy, warianty, sortowanie, zachowanie historii rzędów, zapotrzebowanie niezależne od dostaw, deduplikację, raport PDF oraz integralność dziesięciu dokumentów źródłowych.

## Znane ograniczenia

- Przybliżanie planów PDF korzysta z wbudowanej przeglądarki PDF; część telefonów nie pokazuje PDF w ramce — działają wtedy „Otwórz w nowej karcie” i „Pobierz”.
- Pliki DWG/DXF są zapisywane, ale nie są analizowane. Analiza dotyczy zatwierdzonych źródeł PDF i plików Excel BOM.
- Nie ma jeszcze samodzielnego launchera `ASOLAR.exe` — użyj `Uruchom-Windows.bat`.
