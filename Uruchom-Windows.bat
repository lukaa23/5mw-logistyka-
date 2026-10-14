@echo off
setlocal
cd /d "%~dp0"

where py >nul 2>nul
if errorlevel 1 (
  echo Nie znaleziono programu py. Zainstaluj Python 3.11 z python.org.
  pause
  exit /b 1
)

py -3.11 --version >nul 2>nul
if errorlevel 1 (
  echo Nie znaleziono zainstalowanego Pythona 3.11.
  echo Zainstaluj Python 3.11 z python.org, a nastepnie uruchom ten plik ponownie.
  pause
  exit /b 1
)

if not exist "runtime-packages\.asolar-deps-v2" (
  echo [ASOLAR] Przygotowanie srodowiska przy pierwszym uruchomieniu...
  if not exist "runtime-packages" mkdir "runtime-packages"
  py -3.11 -m pip install --upgrade --target "runtime-packages" -r requirements.txt
  if errorlevel 1 goto :error
  type nul > "runtime-packages\.asolar-deps-v2"
)

if not exist "frontend\dist\index.html" (
  echo Brak zbudowanego interfejsu. Pobierz pelna paczke ASOLAR Enterprise.
  pause
  exit /b 1
)

set "PYTHONPATH=%CD%\runtime-packages;%PYTHONPATH%"
py -3.11 desktop.py
if errorlevel 1 goto :error
exit /b 0

:error
echo.
echo Nie udalo sie uruchomic programu. Sprawdz polaczenie internetowe i instalacje Pythona 3.11.
pause
exit /b 1
