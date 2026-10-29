# ASOLAR v2 — instrukcja użytkownika

ASOLAR v2 obsługuje wiele budów PV. Każda budowa ma własną, odizolowaną przestrzeń danych: strefy, dokumenty, stoły, postęp, dostawy i meldunki jednej budowy nigdy nie mieszają się z inną.

## Role

| Rola | Kto | Co może |
|---|---|---|
| Administrator | konto z uprawnieniem „administrator” | zakłada budowy i konta, widzi wszystkie budowy, usuwa zarchiwizowane budowy |
| Kierownik (na danej budowie) | wybrany w zakładce „Zespół” | wgrywa PDF, zatwierdza propozycje, zarządza strukturą, odbiór QA/QC, edycja/usuwanie WZ i meldunków |
| Brygadzista (na danej budowie) | wybrany w zakładce „Zespół” | montaż stołów, notatki, zdjęcia, przyjęcie WZ, meldunki; podgląd reszty |

Jedno konto może mieć różne role na różnych budowach. Osoba spoza zespołu budowy jej nie widzi.

## Pierwsze kroki

1. **Zaloguj się.** Pierwsze konto to `kierownik` (lokalnie hasło `Asolar2026!`; na serwerze hasło ustawione przy wdrożeniu). Od razu zmień hasło w zakładce **Konta**.
2. **Nowa budowa:** „Moje budowy” → **+ Nowa budowa** (nazwa, lokalizacja, moc). Budowę zmieniasz przełącznikiem w górnym pasku — zakładka zostaje ta sama.
3. **Zespół:** zakładka „Zespół” → dodaj osoby i nadaj im rolę na tej budowie. Nowe konta zakłada administrator (zakładka „Konta”).

## Dokumenty PDF i propozycje

1. „Dokumenty i import” → przeciągnij wiele PDF naraz (BOM, rysunki, planimetrie, instrukcje).
2. Analiza działa w tle, lokalnie na serwerze. Strony-skany są oznaczone „wymaga OCR” (OCR nie jest jeszcze wykonywany).
3. Ekran propozycji: strefy, typy konstrukcji, numeracja stołów, BOM na typ, komponenty, narzędzia, momenty. Każda propozycja ma źródło (plik, strona) i pewność.
4. **Zatwierdź**, **Popraw** (zmień wartość przed zatwierdzeniem) albo **Odrzuć**. „Cofnij decyzję” wycofuje skutki, jeśli dane nie są jeszcze używane.
5. Rozbieżne ilości tej samej pozycji z różnych plików są oznaczone „wymaga potwierdzenia” i nie wchodzą do zatwierdzania zbiorczego.

Nic nie trafia do danych budowy bez zatwierdzenia. Aplikacja niczego nie dopowiada — brakujące dane są puste i oznaczone.

## Rysunki DWG i DXF

- Wgraj `.dwg` lub `.dxf` w „Dokumenty i import” (razem z PDF). Plik DWG/DXF nie otworzy się w przeglądarce — przycisk „Pobierz”, a podgląd rysunku jest w zakładce **Planimetria**.
- Z rysunku powstają propozycje: numeracja stołów (z warstwą, na której jest), strefy, typy konstrukcji, momenty oraz **bloki z liczbą wstawień** (np. `PALO` × 2063). Zatwierdzony blok trafia do katalogu jako ilość kontrolna — porównaj ją z zapotrzebowaniem z BOM.
- **DWG** wymaga konwertera. Jeśli dokument ma status „Błąd odczytu” z prośbą o konwerter: w AutoCAD lub bezpłatnym DWG TrueView zapisz rysunek jako **DXF** i wgraj plik `.dxf` — albo poproś administratora o instalację ODA File Converter.

## Struktura budowy

- **Konstrukcje i BOM:** typy stołów, liczba słupów na stół (uzupełnij — inaczej „wymaga potwierdzenia”), ilości BOM na jeden stół.
- **Stoły i rzędy:** zaznacz stoły i przypisz zbiorczo strefę, rząd, typ. Brak numeracji w PDF (np. skan)? „Dodaj stoły ręcznie” (prefiks + zakres).
- **Zapotrzebowanie:** BOM × liczba stołów danego typu, dla budowy lub strefy; eksport CSV.

## Praca w terenie (telefon)

- Otwórz adres serwera w przeglądarce telefonu i dodaj do ekranu głównego (PWA).
- **Postęp prac:** przycisk „Zamontowany” (brygadzista i kierownik), „Odbiór QC” (kierownik, po montażu). Nazwa stołu otwiera notatki i zdjęcia (aparat telefonu).
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
