#!/usr/bin/env bash
# One-command local dev: API + PWA on http://localhost:8000
set -e
cd "$(dirname "$0")/../backend"
[ -f .env ] && set -a && . ./.env && set +a
pip install -q -r requirements.txt
exec uvicorn app.main:app --host 0.0.0.0 --port "${PORT:-8000}" --reload
