#!/usr/bin/env bash
# Interview Copilot — always uses THIS folder's venv and .env only
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

PYTHON="$ROOT/venv/bin/python"
PIP="$ROOT/venv/bin/pip"

if [[ ! -x "$PYTHON" ]]; then
  echo "Creating interview-copilot venv..."
  python3 -m venv "$ROOT/venv"
fi

if [[ ! -f "$ROOT/.env" ]]; then
  cp "$ROOT/.env.example" "$ROOT/.env"
  echo "Created interview-copilot/.env — add OPENAI_API_KEY"
fi

"$PIP" install -r "$ROOT/requirements.txt" -q

echo "Interview Copilot"
echo "  Folder: $ROOT"
echo "  Python: $PYTHON"
echo "  Config: $ROOT/.env"
echo ""

exec "$PYTHON" "$ROOT/main.py"
