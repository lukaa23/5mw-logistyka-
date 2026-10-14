#!/usr/bin/env sh
set -eu
cd "$(dirname "$0")"

if [ ! -x .venv/bin/python ]; then
  python3 -m venv .venv
  .venv/bin/python -m pip install --upgrade pip
  .venv/bin/python -m pip install -r requirements.txt
fi

test -f frontend/dist/index.html || { echo "Brak frontend/dist. Uruchom: cd frontend && npm install && npm run build"; exit 1; }
exec .venv/bin/python desktop.py
