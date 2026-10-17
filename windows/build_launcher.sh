#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

python3 windows/build_icon.py
x86_64-w64-mingw32-windres windows/asolar-launcher.rc -O coff -o windows/asolar-launcher.res
x86_64-w64-mingw32-gcc \
  -municode -mwindows -Os -s \
  windows/asolar-launcher.c windows/asolar-launcher.res \
  -lshell32 -lws2_32 -o ASOLAR.exe

file ASOLAR.exe
