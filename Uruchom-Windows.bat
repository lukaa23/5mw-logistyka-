@echo off
setlocal
cd /d "%~dp0"

where py >nul 2>nul
if errorlevel 1 (
  echo Nie znaleziono Pythona. Zainstaluj Python 3.11 lub nowszy z python.org.
  pause
  exit /b 1
)

if not exist ".venv\Scripts\python.exe" (
  echo [ASOLAR] Przygotowanie srodowiska przy pierwszym uruchomieniu...
  py -3 -m venv .venv
  if errorlevel 1 goto :error
  ".venv\Scripts\python.exe" -m pip install --upgrade pip
  ".venv\Scripts\python.exe" -m pip install -r requirements.txt
  if errorlevel 1 goto :error
)

if not exist "frontend\dist\index.html" (
  echo Brak zbudowanego interfejsu. Pobierz pelna paczke ASOLAR Enterprise.
  pause
  exit /b 1
)

".venv\Scripts\python.exe" desktop.py
if errorlevel 1 goto :error
exit /b 0

:error
echo.
echo Nie udalo sie uruchomic programu. Sprawdz polaczenie internetowe i Python 3.11+.
pause
exit /b 1
