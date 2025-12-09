#!/bin/bash
set -euo pipefail

SERVICE_NAME="nakrutkaguard"
PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LOG_PREFIX="[NakrutkaGuard][update]"

cd "$PROJECT_ROOT"

echo "$LOG_PREFIX Checking git status..."
if [[ -n "$(git status --porcelain)" ]]; then
  echo "$LOG_PREFIX ❌ Working tree has local changes. Commit/stash them before updating."
  exit 1
fi

if [[ ! -d .git ]]; then
  echo "$LOG_PREFIX ❌ This directory is not a git repository."
  exit 1
fi

echo "$LOG_PREFIX Pulling latest changes..."
git fetch --all --prune
# Fast-forward only to avoid merge commits on server
if ! git merge --ff-only @\{u\}; then
  echo "$LOG_PREFIX ❌ Unable to fast-forward. Resolve manually."
  exit 1
fi

echo "$LOG_PREFIX Rebuilding virtualenv / dependencies..."
./build.sh

echo "$LOG_PREFIX Restarting systemd service $SERVICE_NAME..."
sudo systemctl restart ${SERVICE_NAME}.service

echo "$LOG_PREFIX ✅ Update complete! Service restarted."
