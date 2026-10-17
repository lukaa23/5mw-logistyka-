@echo off
rem Tryb sieciowy: laptop jest serwerem dla telefonow w tej samej sieci Wi-Fi.
rem Zdjecia i notatki zapisuja sie w folderze "data" na tym komputerze.
setlocal
cd /d "%~dp0"
set "ASOLAR_HOST=0.0.0.0"
set "ASOLAR_LAN=1"
echo [ASOLAR] Tryb sieciowy. Adres dla telefonow zostanie wypisany ponizej.
echo [ASOLAR] Przy pierwszym uruchomieniu zezwol programowi na dostep w sieciach PRYWATNYCH (Zapora Windows).
call "%~dp0Uruchom-Windows.bat"
