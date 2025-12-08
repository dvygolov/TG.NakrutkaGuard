#!/bin/bash
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV_DIR="$PROJECT_ROOT/.venv"

if [[ ! -d "$VENV_DIR" ]]; then
  echo "[NakrutkaGuard] Virtualenv not found. Run ./build.sh first."
  exit 1
fi

source "$VENV_DIR/bin/activate"

echo "[NakrutkaGuard] Starting bot..."
nohup "$VENV_DIR/bin/python" -m bot.main \
  >> "$PROJECT_ROOT/nakrutkaguard.log" 2>&1 &
PID=$!

deactivate

echo "[NakrutkaGuard] Bot started with PID $PID. Logs: $PROJECT_ROOT/nakrutkaguard.log"