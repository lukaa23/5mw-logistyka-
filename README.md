# ASOLAR ESET Tracker Manager

Responsywna aplikacja PWA do konfiguracji trackerów ESET, wyliczania zapotrzebowania projektowego, prowadzenia meldunków brygadzisty i kontroli QA/QC na farmie PV.

## Konfiguracja i zapotrzebowanie

Projekt korzysta z czterech zatwierdzonych wariantów: `1x28`, `1x42`, `1x56` i `1x70`. Użytkownik tworzy dowolną liczbę nazwanych stref i w każdej wpisuje liczbę rzędów każdego wariantu. System automatycznie generuje osobne, kolejno numerowane rzędy oraz pokazuje:

- listę elementów potrzebnych na pojedynczy rząd;
- sumę dla liczby rzędów danego wariantu;
- sumę dla całego projektu;
- słupy napędowe, nienapędowe i amortyzatorów;
- podstawy, obudowy łożysk, łożyska polimerowe i reduktory obrotowe;
- rury torsyjne z rozróżnieniem typu, długości i grubości;
- płatwie, elementy amortyzatorów, TCU i odbiornik bezprzewodowy;
- zestawy M10, M12, M14, M16 i M18 wraz z podkładkami oraz momentami dokręcania.

Widok operacyjny pozwala oznaczać każdy wygenerowany rząd jako zbudowany i odebrany QA/QC, prowadzić indywidualne notatki oraz robić zdjęcia bezpośrednio aparatem telefonu. Zmniejszenie liczby rzędów ukrywa nadmiarowe pozycje bez kasowania ich historii; ponowne zwiększenie przywraca wcześniejsze statusy, notatki i zdjęcia.

Widok „Zapotrzebowanie” przedstawia wyłącznie ilości wymagane przez projekt. Nie korzysta ze stanów magazynowych ani fizycznych dostaw WZ.

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
- WebSocket synchronizuje urządzenia, a PWA buforuje odczyty i kolejkuje zapisy offline;
- interfejs działa po polsku na telefonie, tablecie i komputerze.

## Uruchomienie na Windows

1. Pobierz i rozpakuj pełną paczkę ZIP.
2. Zainstaluj Python 3.11 razem z programem Python Launcher (`py`).
3. Uruchom `Uruchom-Windows.bat`.

Skrypt używa polecenia `py -3.11`. Przy pierwszym uruchomieniu instaluje zależności w lokalnym folderze `runtime-packages`, a następnie otwiera aplikację. Dane i zdjęcia są przechowywane w folderze `data`.

## Konta startowe

| Rola | Login | Hasło |
|---|---|---|
| Kierownik Budowy | `kierownik` | `Asolar2026!` |
| Brygadzista | `brygadzista` | `Brygada2026!` |
| Magazynier | `magazynier` | `Magazyn2026!` |

Kierownik może tworzyć kolejne konta. W instalacji sieciowej należy ustawić własny `ASOLAR_SECRET`.

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

Domyślną bazą jest SQLite. Po ustawieniu `DATABASE_URL` i zainstalowaniu sterownika można użyć PostgreSQL.

## Testy

```bash
.venv/bin/python -m unittest -v tests/test_api.py
cd frontend && npm run build
```

Testy sprawdzają strefy, automatyczną numerację rzędów, zachowanie historii, cztery warianty, sumowanie pełnego BOM, momenty dokręcania, role, meldunki, zdjęcia, QA/QC, raport PDF oraz integralność dziesięciu dokumentów źródłowych.
