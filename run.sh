#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")" && pwd)"

start_backend() {
  cd "$ROOT/backend"
  if [ ! -d .venv ]; then
    python3 -m venv .venv
    .venv/bin/pip install -r requirements.txt
  fi
  source .venv/bin/activate
  uvicorn app.main:app --reload --port "${BACKEND_PORT:-8000}" --log-level info
}

start_frontend() {
  cd "$ROOT/frontend"
  if [ ! -d node_modules ]; then
    npm install
  fi
  npm run dev
}

case "${1:-}" in
  backend) start_backend ;;
  frontend) start_frontend ;;
  *)
    echo "Usage: ./run.sh backend|frontend"
    exit 1
    ;;
esac
