#!/usr/bin/env bash
set -e
cd "$(dirname "$0")"
if [[ ! -d .venv ]]; then
 python3 -m venv .venv
 source .venv/bin/activate
 python -m pip install -r requirements.txt
 python manage.py add-user
else
 source .venv/bin/activate
fi
exec python -m uvicorn backend.main:app --host 0.0.0.0 --port 8000
