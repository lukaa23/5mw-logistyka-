# ASOLAR v2 — instrukcja użytkownika

ASOLAR v2 obsługuje wiele budów PV. Każda budowa ma własną, odizolowaną przestrzeń danych: strefy, dokumenty, stoły, postęp, dostawy i meldunki jednej budowy nigdy nie mieszają się z inną.

## Role

| Rola | Kto | Co może |
|---|---|---|
| Administrator | konto z uprawnieniem „administrator” | zakłada budowy i konta, widzi wszystkie budowy, usuwa zarchiwizowane budowy |
| Kierownik (na danej budowie) | wybrany w zakładce „Zespół” | wgrywa PDF, zatwierdza propozycje, zarządza strukturą, odbiór QA/QC, edycja/usuwanie WZ i meldunków |
| Brygadzista (na danej budowie) | wybrany w zakładce „Zespół” | montaż stołów, notatki, zdjęcia, przyjęcie WZ, meldunki; podgląd reszty |

Jedno konto może mieć różne role na różnych budowach. Osoba spoza zespołu budowy jej nie widzi.

## Ekran aplikacji (jak w v1)

- **Panel boczny** (po lewej): Pulpit, Budowy, Strefy i rzędy, Meldunki, Zapotrzebowanie, Dostawy na budowę, Mapa / Planimetria, Dokumenty, Konstrukcje i BOM, Zespół, Ustawienia budowy. Na telefonie — pasek na dole ekranu (tam „Rzędy” to widok operacyjny).
- **Górny pasek:** „Aktywna budowa” — wybierz inną farmę z listy, a aplikacja zostanie w tym samym widoku. Obok wskaźnik **Online/Offline** z liczbą niewysłanych zmian (kliknij, aby je zobaczyć lub wysłać).

## Pierwsze kroki

1. **Zaloguj się.** Pierwsze konto to `kierownik` (lokalnie hasło `Asolar2026!`; na serwerze hasło ustawione przy wdrożeniu). Od razu zmień hasło w zakładce **Konta**.
2. **Nowa budowa:** „Moje budowy” → **+ Nowa budowa** (nazwa, lokalizacja, moc). Budowę zmieniasz przełącznikiem w górnym pasku — zakładka zostaje ta sama.
3. **Zespół:** zakładka „Zespół” → dodaj osoby i nadaj im rolę na tej budowie. Nowe konta zakłada administrator (zakładka „Konta”).

## Dokumenty: dodawanie i sprawdzanie (3 kroki)

1. **Dodaj:** zakładka „Dokumenty” → upuść pliki na właściwy kafelek — **BOM / lista materiałowa**, **Rysunki i schematy** (PDF, DWG, DXF) albo **Instrukcje i manuale** — lub kliknij „Wybierz pliki z dysku”. Można wiele plików naraz; każdy ma własny pasek postępu.
2. **Sprawdź:** przy pliku kliknij **Sprawdź**. Po lewej podgląd dokumentu (strony, „Powiększ”), po prawej odczytane pozycje (nazwa, ilość, kod) ze statusem **Wymaga potwierdzenia** / **Zatwierdzone**. Kliknięcie pozycji otwiera ją do poprawki i pokazuje jej stronę w podglądzie.
3. **Zatwierdź:** ✓ przy pozycji albo **Zatwierdź wszystkie**. Pozycjom BOM bez typu stołu wpisz typ jednym polem („Ustaw i zatwierdź”).

Rodzaj dokumentu decyduje, co aplikacja odczytuje: z BOM — pozycje i typy stołów, z rysunku — numerację, strefy, typy i bloki, z instrukcji — momenty, narzędzia i tabele przypisane do typu. Zły rodzaj? Zmień go na ekranie sprawdzania — plik zostanie odczytany ponownie.

Gdy aplikacja nic nie odczyta (skan, nietypowy układ), dokument ma status **Uzupełnij ręcznie** — to nie błąd: obok podglądu jest formularz „Dodaj pozycję ręcznie” (przepisz dane ze strony, „Dodaj i zatwierdź”). Aplikacja nie zgaduje — pozycje niepewne nie są proponowane.

## Rysunki DWG i DXF

- Wgraj `.dwg` lub `.dxf` w zakładce „Dokumenty” (razem z PDF). Plik DWG/DXF nie otworzy się w przeglądarce — przycisk „Pobierz”, a podgląd rysunku jest w zakładce **Planimetria**.
- Z rysunku powstają propozycje: numeracja stołów (z warstwą, na której jest), strefy, typy konstrukcji, momenty oraz **bloki z liczbą wstawień** (np. `PALO` × 2063). Zatwierdzony blok trafia do katalogu jako ilość kontrolna — porównaj ją z zapotrzebowaniem z BOM.
- **DWG** wymaga konwertera. Jeśli dokument ma status „Błąd odczytu” z prośbą o konwerter: w AutoCAD lub bezpłatnym DWG TrueView zapisz rysunek jako **DXF** i wgraj plik `.dxf` — albo poproś administratora o instalację ODA File Converter.

## Strefy i rzędy (jak w v1)

Panel boczny → **Strefy i rzędy** → „Konfiguracja stref”:

1. **Strefa:** po lewej „+ Nowa strefa” — nazwa i opis.
2. **Rzędy:** „Dodaj rzędy do strefy” — prefiks (podpowiedź: A, B, C… dla kolejnych stref), od, do (np. 1–50) i opcjonalnie wariant.
3. **Warianty:** u góry „Warianty stołów na tej budowie” — dodaj warianty występujące na tej farmie (np. 1x28, 1x42, 1x56+1x42). Przypisz je do zakresu („Przypisz wariant do rzędów”: od–do) albo pojedynczo w tabeli rzędów.

Tabela rzędów pokazuje wariant, montaż, odbiór QA/QC i pamięć rzędu (kliknij numer rzędu: notatki i zdjęcia). „Protokół PDF” — protokół montażu i odbioru strefy do podpisu.

Widok **Rzędy operacyjne** (na telefonie: „Rzędy”) służy do pracy w terenie: „Zamontowany”, „Odbiór QC”, notatki i zdjęcia — także bez zasięgu.

**Konstrukcje i BOM** — ilości materiałów na jeden stół każdego wariantu; **Zapotrzebowanie** liczy BOM × liczbę rzędów danego wariantu.

## Praca w terenie (telefon)

- Otwórz adres serwera w przeglądarce telefonu i dodaj do ekranu głównego (PWA).
- **Rzędy operacyjne** („Strefy i rzędy”; na telefonie „Rzędy”): przycisk „Zamontowany” (brygadzista i kierownik), „Odbiór QC” (kierownik, po montażu). Nazwa stołu otwiera notatki i zdjęcia (aparat telefonu).
- **Bez zasięgu:** zmiany zapisują się w telefonie („czeka na wysłanie”) i wysyłają się same po powrocie sieci. Licznik w górnym pasku pokazuje niewysłane zmiany; tam można je też wysłać ręcznie lub odrzucić.
- **Meldunki:** dzienny meldunek brygady z liczbą osób i godzin, dziennikiem QA/QC i zdjęciami — także offline.
- **Dostawy i magazyn:** przyjęcie WZ (pozycje z katalogu materiałów budowy), stan: potrzeba / dostarczono / uszkodzone / bilans.

## Planimetria i raporty

- **Planimetria:** wybierz rysunek i stronę. Znaczniki stołów są w miejscach, gdzie ich oznaczenia (np. `T.48`) są wydrukowane na rysunku; kolor = stan (czerwony: do montażu, żółty: zamontowany, zielony: odebrany). Kliknięcie otwiera panel stołu. Rysunek-skan nie ma znaczników.
- **Przegląd:** pulpit postępu i prognoza zakończenia (tylko z rzeczywistych dat montażu, zawsze z założeniami).
- **Raport dzienny PDF:** Przegląd → wybierz datę → „Pobierz raport”.

## Archiwizacja i usuwanie budowy

„Ustawienia” → **Archiwizuj** (budowa znika z listy aktywnych i nie przyjmuje zmian; można przywrócić). Usunięcie na stałe: tylko administrator, tylko zarchiwizowaną budowę, po przepisaniu nazwy — kasuje wyłącznie dane tej budowy.

## Aplikacja na komputer (Windows)

Instalator `ASOLAR-v2-…-instalator.exe` (lub wersja przenośna). Przy pierwszym uruchomieniu wybierz:

- **Serwer w chmurze** — wpisz adres HTTPS serwera v2 (zalecane: wspólne dane z telefonami),
- **Serwer na tym komputerze** — wymaga Pythona 3.11; dane w profilu użytkownika (menu Plik → „Otwórz folder danych”).
