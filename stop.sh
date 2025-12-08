#!/bin/bash
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Ищем процесс по bot.main
PIDS=$(pgrep -f "bot.main" || true)

if [[ -z "$PIDS" ]]; then
  echo "[NakrutkaGuard] Bot is not running"
  exit 0
fi

echo "[NakrutkaGuard] Stopping bot processes: $PIDS"
kill $PIDS

echo "[NakrutkaGuard] Bot stopped"
