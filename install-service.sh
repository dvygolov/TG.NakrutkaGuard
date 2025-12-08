#!/bin/bash
set -euo pipefail

SERVICE_NAME="nakrutkaguard"
SERVICE_FILE="/etc/systemd/system/${SERVICE_NAME}.service"

# Check for uninstall flag
if [[ "${1:-}" == "-u" ]]; then
  echo "=== Uninstalling NakrutkaGuard systemd service ==="
  
  # Stop and disable service
  if systemctl is-active --quiet ${SERVICE_NAME}.service; then
    echo "Stopping service..."
    sudo systemctl stop ${SERVICE_NAME}.service
  fi
  
  if systemctl is-enabled --quiet ${SERVICE_NAME}.service; then
    echo "Disabling service..."
    sudo systemctl disable ${SERVICE_NAME}.service
  fi
  
  # Remove service file
  if [[ -f "$SERVICE_FILE" ]]; then
    echo "Removing service file..."
    sudo rm "$SERVICE_FILE"
    sudo systemctl daemon-reload
  fi
  
  echo "✅ Service ${SERVICE_NAME} successfully uninstalled!"
  exit 0
fi

echo "=== Installing NakrutkaGuard systemd service ==="

# 1. Get current directory (where script is located)
DIST_PATH="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
echo "📦 Working directory: $DIST_PATH"

# Ensure virtualenv exists
if [[ ! -d "$DIST_PATH/.venv" ]]; then
  echo "⚙️  Virtualenv not found, running build.sh ..."
  "$DIST_PATH/build.sh"
fi

PY_BIN="$DIST_PATH/.venv/bin/python"

if [[ ! -x "$PY_BIN" ]]; then
  echo "❌ Python executable not found at $PY_BIN"
  exit 1
fi

# 2. User to run the service
read -r -p "Enter Linux username to run the service (Enter = $USER): " SERVICE_USER
SERVICE_USER=${SERVICE_USER:-$USER}

# 4. Create systemd unit
echo "Creating systemd service: $SERVICE_FILE"

sudo bash -c "cat > $SERVICE_FILE" <<EOF
[Unit]
Description=NakrutkaGuard Telegram Bot
After=network.target

[Service]
Type=simple
WorkingDirectory=$DIST_PATH
ExecStart=$PY_BIN -m bot.main
Restart=always
RestartSec=5
EnvironmentFile=-$DIST_PATH/.env
User=$SERVICE_USER
Group=$SERVICE_USER
StandardOutput=append:$DIST_PATH/nakrutkaguard.service.log
StandardError=append:$DIST_PATH/nakrutkaguard.service.log

[Install]
WantedBy=multi-user.target
EOF

# 5. Reload systemd and enable service
sudo systemctl daemon-reload
sudo systemctl enable ${SERVICE_NAME}.service
sudo systemctl restart ${SERVICE_NAME}.service

echo "✅ Service ${SERVICE_NAME} successfully installed and started!"
echo "📦 Working directory: $DIST_PATH"
echo "🔄 Autostart on reboot: ENABLED"
echo ""
echo "📌 Service management:"
echo "  Check status:   sudo systemctl status ${SERVICE_NAME}"
echo "  Stop:           sudo systemctl stop ${SERVICE_NAME}"
echo "  Start:          sudo systemctl start ${SERVICE_NAME}"
echo "  Restart:        sudo systemctl restart ${SERVICE_NAME}"
echo "  Logs:           tail -f $DIST_PATH/nakrutkaguard.service.log"
