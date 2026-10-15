# ASOLAR Universal PV Construction Manager

Responsywna aplikacja PWA do zarządzania budową farm fotowoltaicznych. System nie narzuca wariantów, długości ani zamkniętego słownika prac: projekt, sekcje, każdy rząd, materiały i meldunki można opisać zgodnie ze stanem faktycznym.

Zakres instrukcji generowanych z dokumentacji obejmuje konstrukcję mechaniczną. Parser pomija elektrykę, okablowanie, uziemienie i wbijanie słupów.

## Zatwierdzona baza źródłowa

Program zawiera w folderze `project_sources` dokładnie pięć dokumentów dostarczonych dla projektu RF-GIULIETTA:

1. `łaczenia rur.pdf` — rysunki warsztatowe słupów QZ1–QZ4, FZ1–FZ2 i NZ1;
2. `planimetria.pdf` — rysunki wariantów 1PX28/42/56/70 i tabele BOM;
3. `planimetria 6,5mw.pdf` — planimetria RF-GIULIETTA, Momo, 6,4915 MWp;
4. `montaż mechaniczny.pdf` — instrukcje mechaniczne, narzędzia, momenty i tabele wariantów;
5. `manual v.2.pdf` — pełny manual producenta ESET Solar.

Manifest [source-manifest.json](project_sources/source-manifest.json) zapisuje sumy SHA-256, strony źródłowe, zakres oraz dane używane przez aplikację. Przy pierwszym uruchomieniu pięć plików jest automatycznie rejestrowanych w projekcie. Inny wgrany plik pozostaje dokumentem pomocniczym i nie zmienia instrukcji ani kalkulatora.

Instrukcje obejmują wyłącznie montaż podstaw przekładni i łożysk, przekładni, obudów łożysk, rur momentowych, płatwi, amortyzatorów i zaślepek. Wyłączone są: wbijanie i montaż słupów, TCU, odbiornik bezprzewodowy, moduły PV, okablowanie, uziemienie i uruchomienie elektryczne.

## Uruchomienie na Windows

1. Pobierz i rozpakuj pełną paczkę ZIP.
2. Zainstaluj [Python 3.11](https://www.python.org/downloads/release/python-3119/) wraz z programem Python Launcher (`py`).
3. Uruchom `Uruchom-Windows.bat`.
4. Skrypt sprawdzi interpreter przez `py -3.11`, a przy pierwszym uruchomieniu pobierze zależności do lokalnego folderu `runtime-packages`.

Program otworzy się automatycznie. Dane i zdjęcia są przechowywane w folderze `data`, dlatego nie należy go usuwać podczas aktualizacji aplikacji.

## Konta startowe

| Rola | Login | Hasło |
|---|---|---|
| Kierownik Budowy | `kierownik` | `Asolar2026!` |
| Brygadzista | `brygadzista` | `Brygada2026!` |
| Magazynier | `magazynier` | `Magazyn2026!` |

Kierownik może tworzyć indywidualne konta. W instalacji sieciowej należy ustawić własny `ASOLAR_SECRET`.

## Najważniejsze zasady działania

### Projekty i rzędy

- projekty można dodawać, edytować, archiwizować, przywracać i usuwać;
- projekt przechowuje nazwę, lokalizację, moc oraz dowolny opis typu struktury;
- użytkownik tworzy własne strefy i sekcje;
- każdy rząd ma osobne: oznaczenie, wariant, długość, specyfikację i ręczne ilości materiałów;
- wybór szablonu jedynie uzupełnia formularz — wszystkie wartości można później nadpisać;
- system nie skaluje ilości automatycznie na podstawie długości.

### Kalkulator

- program startuje z potwierdzonymi wariantami `1x28`, `1x42`, `1x56` i `1x70`;
- ilości startowe z tabel wynoszą odpowiednio: 5/8/10/13 rur S156 oraz 30/44/58/73 płatwie i komplety mocowania;
- komplet mocowania oznacza: U-bolt UM10×166×188×30, BP095, dwie podkładki BP069 i dwie nakrętki M10, moment 25–32 N·m;
- użytkownik może także zapisać własny wariant specjalny;
- konfiguracja zapamiętuje typ konstrukcji, długość informacyjną, specyfikację oraz ilości trzech części na rząd;
- przed każdym obliczeniem można ręcznie zmienić każdą ilość;
- wynik mnoży wyłącznie wartości wpisane przez użytkownika przez liczbę rzędów.

### Magazyn i pole

Logistyka używa dokładnie trzech edytowalnych pozycji materiałowych. Dla każdej z nich system przechowuje:

1. całkowite zapotrzebowanie projektu;
2. fizyczne dostawy z dokumentów WZ;
3. ilość uszkodzoną;
4. aktualny stan na polu i bilans do zapotrzebowania.

Nowy projekt zawsze rozpoczyna ze stanem na polu równym `0`. Samo wpisanie zapotrzebowania nie zwiększa stanu. Stan rośnie dopiero po zarejestrowaniu dostawy WZ.

### Meldunki brygadzisty

- dowolny opis wykonanych prac bez zamkniętego słownika;
- liczba zbudowanych rzędów, ludzi oraz godzin;
- osobny dziennik QA/QC i pozostałe notatki;
- opcjonalne przypisanie meldunku do rzędu;
- zdjęcie bezpośrednio z aparatu telefonu i historia fotografii;
- edycja oraz usuwanie meldunków zgodnie z rolą użytkownika.

## Pozostałe moduły

- status wykonania rzędu z autorem i czasem;
- osobny odbiór QA/QC wykonywany przez kierownika;
- RFI ze zdjęciem, priorytetem i statusem;
- pięć wbudowanych dokumentów źródłowych oraz pliki pomocnicze PDF, DWG, DXF, XLSX/XLSM;
- instrukcje krok po kroku po polsku ze wskazaniem dokumentu, strony i punktu kontroli;
- raport dzienny PDF z pracami, KPI oraz dziennikiem QA/QC;
- synchronizacja WebSocket między urządzeniami;
- pamięć odczytów i kolejka zapisów offline;
- responsywny interfejs PWA po polsku.

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

Do pracy z odświeżaniem frontendu uruchom backend, a w drugim terminalu:

```bash
cd frontend
npm run dev
```

Dokumentacja OpenAPI jest dostępna pod ścieżką `/docs` działającego serwera.

## Docker

```bash
ASOLAR_SECRET="długi-losowy-klucz" docker compose up --build
```

Domyślną bazą jest SQLite. Warstwa SQLAlchemy umożliwia użycie PostgreSQL po ustawieniu `DATABASE_URL` i doinstalowaniu odpowiedniego sterownika.

## Dodatkowe pliki

Interfejs przyjmuje PDF, DWG, DXF oraz XLSX/XLSM, aby przechować je przy projekcie. Zgodnie z polityką źródeł nie są one używane do generowania instrukcji, ilości ani momentów dokręcania. Oryginalne pięć plików można zawsze pobrać z modułu „Dokumenty”.

## Testy

```bash
.venv/bin/python -m unittest -v tests/test_api.py
cd frontend && npm run build
```

Test integracyjny sprawdza elastyczne projekty i rzędy, szablony z ręcznymi korektami, trzy materiały, zerowy stan początkowy pola, WZ, dowolny opis pracy, QA/QC, zdjęcia, role, archiwizację i raport PDF.
