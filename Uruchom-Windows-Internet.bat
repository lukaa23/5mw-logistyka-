@echo off
rem Tryb internetowy: laptop jest serwerem dostepnym z telefonu z dowolnego miejsca (Tailscale Funnel, HTTPS).
rem Aplikacja nasluchuje tylko lokalnie (127.0.0.1) - na zewnatrz wystawia ja wylacznie Tailscale.
rem Zdjecia i notatki zapisuja sie w folderze "data" na tym komputerze.
setlocal
cd /d "%~dp0"
set "ASOLAR_HOST=127.0.0.1"
set "PORT=8765"

where tailscale >nul 2>nul
if errorlevel 1 (
  echo [ASOLAR] Nie znaleziono Tailscale. Zainstaluj go z tailscale.com/download i zaloguj sie, a potem uruchom ten plik ponownie.
  echo [ASOLAR] Szczegoly: README, rozdzial "Dostep z internetu".
  pause
  exit /b 1
)

echo [ASOLAR] Wlaczam publiczny adres HTTPS (Tailscale Funnel) dla portu %PORT%...
tailscale funnel --bg %PORT%
if errorlevel 1 (
  echo [ASOLAR] Nie udalo sie wlaczyc Funnel. Sprawdz, czy w panelu Tailscale wlaczono HTTPS oraz Funnel (README).
  pause
  exit /b 1
)
echo.
tailscale funnel status
echo.
echo [ASOLAR] Adres https://... powyzej wpisz w telefonie. Laptop musi byc wlaczony, z internetem i bez uspienia.
echo [ASOLAR] Haslo kierownika musi byc dlugie i unikalne - adres jest publiczny.
echo.
call "%~dp0Uruchom-Windows.bat"
tailscale funnel --https=443 off >nul 2>nul
