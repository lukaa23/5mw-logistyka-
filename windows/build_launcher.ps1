# Buduje ASOLAR.exe na Windows przy użyciu MinGW-w64 (np. MSYS2: pacman -S mingw-w64-ucrt-x86_64-gcc).
# Uruchomienie z katalogu repozytorium:  powershell -ExecutionPolicy Bypass -File windows\build_launcher.ps1
$ErrorActionPreference = "Stop"
Set-Location (Join-Path $PSScriptRoot "..")

foreach ($tool in @("gcc", "windres")) {
    if (-not (Get-Command $tool -ErrorAction SilentlyContinue)) {
        Write-Error "Nie znaleziono programu '$tool'. Zainstaluj MinGW-w64 (np. MSYS2 UCRT64) i dodaj jego katalog bin do PATH."
    }
}

py -3.11 windows\build_icon.py
windres windows\asolar-launcher.rc -O coff -o windows\asolar-launcher.res
gcc -municode -mwindows -Os -s windows\asolar-launcher.c windows\asolar-launcher.res -lshell32 -lws2_32 -o ASOLAR.exe
Get-Item ASOLAR.exe | Select-Object Name, Length, LastWriteTime
