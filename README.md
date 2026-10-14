# Logistyka Struktury

Lokalny program do organizacji montażu mechanicznego konstrukcji trackerów. Zakres nie obejmuje elektryki, modułów PV ani wbijania słupów.

## Uruchomienie na Windows

1. Rozpakuj cały plik ZIP.
2. Otwórz folder `Logistyka-Struktury`.
3. Uruchom `Uruchom-Windows.bat`.
4. Program otworzy się w domyślnej przeglądarce.

Wymagany jest Python 3.10 lub nowszy. Dane są zapisywane lokalnie w folderze `data`. Nie zamykaj czarnego okna podczas pracy programu.

## Linux

Uruchom `./uruchom-linux.sh`. Jeśli plik nie ma prawa uruchomienia: `chmod +x uruchom-linux.sh`.

## Funkcje

- kalkulator wariantów 1P×28, 1P×42, 1P×56 i 1P×70;
- zestawienie rur, płatwi, śrub U, podkładek, nakrętek i narzędzi;
- zapas materiałowy i obsługa wielu rzędów;
- wgrywanie PDF, DWG i DXF;
- instrukcja montażu krok po kroku;
- godziny pracy, postęp, kontrola jakości i sprzęt.

Kalkulator dobiera najbliższy wariant według długości rur z instrukcji producenta. Ilości niepodane w tabelach producenta są oznaczone jako wymagające potwierdzenia w aktualnym BOM i rysunku wykonawczym.
