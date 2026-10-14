# ASOLAR Enterprise Construction & Logistics Manager

Responsywna aplikacja PWA do zarządzania montażem mechanicznym konstrukcji na farmach fotowoltaicznych. Łączy strukturę projektu, wykonanie i odbiory QA/QC, dokumentację, RFI, dostawy, czas pracy, kalkulator BOM oraz raporty PDF.

Zakres instrukcji montażowych celowo obejmuje konstrukcję mechaniczną. Parser odrzuca sekcje dotyczące elektryki, okablowania, uziemienia i wbijania słupów.

## Najszybsze uruchomienie na Windows

1. Pobierz i rozpakuj pełną paczkę ZIP.
2. Zainstaluj [Python 3.11 lub nowszy](https://www.python.org/downloads/) i podczas instalacji zaznacz dodanie Pythona do systemu.
3. Uruchom `Uruchom-Windows.bat`.
4. Skrypt sprawdzi Python 3.11 przez `py -3.11`, a przy pierwszym uruchomieniu pobierze zależności do lokalnego folderu `runtime-packages`. Następnie program otworzy się pod adresem `http://127.0.0.1:8765`.

Dane i wgrane dokumenty są przechowywane w folderze `data`. Nie usuwaj tego folderu, jeśli chcesz zachować historię.

## Konta startowe

| Rola | Login | Hasło |
|---|---|---|
| Kierownik Budowy | `kierownik` | `Asolar2026!` |
| Brygadzista | `brygadzista` | `Brygada2026!` |
| Magazynier | `magazynier` | `Magazyn2026!` |

Kierownik może utworzyć indywidualne konta w module **Użytkownicy**. W instalacji dostępnej w sieci ustaw własny `ASOLAR_SECRET` i zmień konta startowe.

## Uruchomienie deweloperskie

Wymagane są Python 3.11+ oraz Node.js 20+.

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
cd frontend
npm install
npm run build
cd ..
.venv/bin/python server.py
```

Aplikacja działa pod adresem `http://127.0.0.1:8765`, a dokumentacja API pod `http://127.0.0.1:8765/docs`.

Do pracy nad frontendem z odświeżaniem na żywo uruchom w dwóch terminalach:

```bash
.venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8765 --reload
cd frontend && npm run dev
```

## Docker

```bash
ASOLAR_SECRET="długi-losowy-klucz" docker compose up --build
```

SQLite jest ustawieniem domyślnym. Warstwa SQLAlchemy obsługuje też relacyjną bazę PostgreSQL po ustawieniu `DATABASE_URL` i doinstalowaniu sterownika PostgreSQL.

## Moduły

- role: Kierownik Budowy, Brygadzista i Magazynier;
- projekt → dowolna liczba stref → sekcje → rzędy / stoły;
- zbiorcze tworzenie rzędów i wybór wariantu konstrukcji;
- status wykonania z autorem i czasem oraz osobny odbiór QA/QC;
- archiwizacja sekcji dopiero po odebraniu wszystkich rzędów;
- zdjęcia z aparatu telefonu przypisane do rzędu lub RFI;
- parser PDF dla mechanicznych kroków montażowych i momentów dokręcania;
- import BOM z XLSX i relacje typ rzędu → komponent → ilość / moment;
- przechowywanie plików PDF, DWG, DXF, XLSX/XLSM;
- kalkulator materiałów, śrub, podkładek i narzędzi według długości oraz liczby rzędów;
- alerty RFI z priorytetem, zdjęciem i statusem;
- rejestr WZ, ilości uszkodzone i bilans zapotrzebowania do dostaw;
- czas pracy, manogodziny, tempo montażu i prognoza zakończenia;
- raport dzienny PDF dla inwestora;
- WebSocket do odświeżania wielu urządzeń;
- PWA, pamięć podręczna odczytów i kolejka zapisów offline z deduplikacją.

## Format BOM Excel

Parser wyszukuje w pierwszych 20 wierszach nagłówki w języku polskim lub angielskim. Najprostszy arkusz zawiera:

| typ_rzedu | typ_konstrukcji | dlugosc_m | sku | nazwa | kategoria | ilosc | jednostka | moment_min | moment_max |
|---|---|---:|---|---|---|---:|---|---:|---:|
| 1P×42 | tracker 1-noga | 57.946 | M10-NUT | Nakrętka M10 | Śruby | 88 | szt. | 25 | 32 |

Obsługiwane aliasy obejmują m.in. `row_type`, `tracker_type`, `part_no`, `component`, `qty`, `per_row`, `unit`, `torque_min` i `torque_max`.

PDF z tekstem jest analizowany lokalnie. Skan bez warstwy tekstowej wymaga wcześniejszego OCR. Plik DWG jest bezpiecznie przechowywany; aby analizować jego opisy i geometrię, dodaj także eksport PDF lub DXF. BOM materiałowy należy potwierdzić zatwierdzoną rewizją projektu przed wydaniem na budowę.

## Testy

```bash
.venv/bin/python -m unittest -v tests/test_api.py
cd frontend && npm run build
```

Test integracyjny przechodzi przez role, strukturę projektu, wykonanie, QA/QC, blokadę archiwizacji, RFI, WZ, kalkulator, KPI i generowanie PDF.
