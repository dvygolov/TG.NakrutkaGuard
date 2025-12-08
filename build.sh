#!/bin/bash
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV_DIR="$PROJECT_ROOT/.venv"

echo "[NakrutkaGuard] Preparing virtual environment in $VENV_DIR"

if [[ ! -d "$VENV_DIR" ]]; then
  python3 -m venv "$VENV_DIR"
fi

source "$VENV_DIR/bin/activate"

echo "[NakrutkaGuard] Upgrading pip & wheel..."
pip install --upgrade pip wheel >/dev/null

echo "[NakrutkaGuard] Installing project requirements..."
pip install -r "$PROJECT_ROOT/requirements.txt"

deactivate

echo "[NakrutkaGuard] Environment ready. Use $VENV_DIR/bin/python -m bot.main to run the bot."