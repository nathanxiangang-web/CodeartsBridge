#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="${BRIDGE_REPO:-$(cd "$SCRIPT_DIR/.." && pwd)}"
VENV_DIR="${BRIDGE_VENV:-$REPO_DIR/.venv}"
PYTHON_BIN="${PYTHON_BIN:-python3}"
BRIDGE_HOST="${BRIDGE_HOST:-0.0.0.0}"
BRIDGE_PORT="${BRIDGE_PORT:-8080}"
BRIDGE_WITH_PIPELINE="${BRIDGE_WITH_PIPELINE:-1}"
BRIDGE_INSTALL_SYSTEMD="${BRIDGE_INSTALL_SYSTEMD:-1}"
SERVICE_NAME="${BRIDGE_SERVICE_NAME:-bridge}"
RUN_USER="${BRIDGE_USER:-${SUDO_USER:-$(id -un)}}"

if command -v getent >/dev/null 2>&1; then
  RUN_HOME="$(getent passwd "$RUN_USER" | cut -d: -f6)"
else
  RUN_HOME="$HOME"
fi
RUN_HOME="${RUN_HOME:-$HOME}"

echo "=== CodeartsBridge Bridge Installer ==="
echo "repo:     $REPO_DIR"
echo "venv:     $VENV_DIR"
echo "user:     $RUN_USER"
echo "listen:   $BRIDGE_HOST:$BRIDGE_PORT"
echo "pipeline: $BRIDGE_WITH_PIPELINE"

cd "$REPO_DIR"

if ! command -v "$PYTHON_BIN" >/dev/null 2>&1; then
  echo "ERROR: Python not found: $PYTHON_BIN" >&2
  exit 1
fi

if [ ! -f "$REPO_DIR/pyproject.toml" ]; then
  echo "ERROR: not a CodeartsBridge checkout: $REPO_DIR" >&2
  exit 1
fi

"$PYTHON_BIN" -m venv "$VENV_DIR"
"$VENV_DIR/bin/python" -m pip install --upgrade pip >/dev/null
"$VENV_DIR/bin/python" -m pip install -e "$REPO_DIR"

"$VENV_DIR/bin/python" -m bridge.cli bootstrap
"$VENV_DIR/bin/python" -m bridge.cli doctor
"$VENV_DIR/bin/python" -m bridge.cli --help >/dev/null

if [ "$BRIDGE_INSTALL_SYSTEMD" != "1" ]; then
  echo "systemd install skipped (BRIDGE_INSTALL_SYSTEMD=$BRIDGE_INSTALL_SYSTEMD)"
  echo "Run manually:"
  if [ "$BRIDGE_WITH_PIPELINE" = "1" ]; then
    echo "  $VENV_DIR/bin/python -m bridge.cli serve --host $BRIDGE_HOST --port $BRIDGE_PORT --with-pipeline"
  else
    echo "  $VENV_DIR/bin/python -m bridge.cli serve --host $BRIDGE_HOST --port $BRIDGE_PORT"
  fi
  exit 0
fi

PIPELINE_ARG=""
if [ "$BRIDGE_WITH_PIPELINE" = "1" ]; then
  PIPELINE_ARG=" --with-pipeline"
fi

UNIT_FILE="/etc/systemd/system/$SERVICE_NAME.service"
TMP_UNIT="$(mktemp)"
trap 'rm -f "$TMP_UNIT"' EXIT

cat >"$TMP_UNIT" <<EOF
[Unit]
Description=CodeartsBridge Server
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=$RUN_USER
WorkingDirectory=$REPO_DIR
Environment=PYTHONUNBUFFERED=1
Environment=HOME=$RUN_HOME
ExecStart=$VENV_DIR/bin/python -m bridge.cli serve --host $BRIDGE_HOST --port $BRIDGE_PORT$PIPELINE_ARG
Restart=on-failure
RestartSec=3
KillMode=mixed

[Install]
WantedBy=multi-user.target
EOF

sudo cp "$TMP_UNIT" "$UNIT_FILE"
sudo systemctl daemon-reload
sudo systemctl enable "$SERVICE_NAME" >/dev/null
sudo systemctl restart "$SERVICE_NAME"

echo "Installed: $UNIT_FILE"
echo "Status:"
sudo systemctl --no-pager --full status "$SERVICE_NAME" || true

if command -v curl >/dev/null 2>&1; then
  sleep 1
  if curl -fsS "http://127.0.0.1:$BRIDGE_PORT/api/health" >/dev/null; then
    echo "Health: OK"
  else
    echo "WARNING: bridge service started but /api/health is not reachable yet" >&2
  fi
fi

echo "=== Done ==="
echo "UI: http://<bridge-host>:$BRIDGE_PORT"
echo "Logs: journalctl -u $SERVICE_NAME -f"
