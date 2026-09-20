#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="${BRIDGE_REPO:-$(cd "$SCRIPT_DIR/.." && pwd)}"
VENV_DIR="${BRIDGE_VENV:-$REPO_DIR/.venv}"
PYTHON_BIN="${PYTHON_BIN:-python3}"
AGENT_ROOT="${BRIDGE_AGENT_ROOT:-$HOME/.codex-glm-bridge/agent}"
CONFIG_DIR="${BRIDGE_CONFIG_DIR:-$HOME/.config/codeartsbridge}"
AGENT_PORT="${BRIDGE_AGENT_PORT:-8765}"
AGENT_CAPACITY="${BRIDGE_AGENT_CAPACITY:-1}"
BRIDGE_INSTALL_SYSTEMD="${BRIDGE_INSTALL_SYSTEMD:-1}"
SERVICE_NAME="${BRIDGE_AGENT_SERVICE_NAME:-bridge-worker-agent}"
RUN_USER="${BRIDGE_USER:-${SUDO_USER:-$(id -un)}}"
AUTH_MODE="${BRIDGE_AGENT_AUTH:-auto}"
EXPECTED_CODEARTS_VERSION="${BRIDGE_CODEARTS_EXPECTED_VERSION:-}"
DISABLE_CODEARTS_AUTO_UPDATE="${CODEARTS_DISABLE_AUTO_UPDATE:-true}"

if command -v getent >/dev/null 2>&1; then
  RUN_HOME="$(getent passwd "$RUN_USER" | cut -d: -f6)"
else
  RUN_HOME="$HOME"
fi
RUN_HOME="${RUN_HOME:-$HOME}"
CODEARTS_ENV_FILE="${BRIDGE_CODEARTS_ENV_FILE:-$RUN_HOME/.config/codeartsbridge/codearts.env}"

echo "=== CodeartsBridge Worker Agent Installer ==="
echo "repo:     $REPO_DIR"
echo "venv:     $VENV_DIR"
echo "user:     $RUN_USER"
echo "listen:   0.0.0.0:$AGENT_PORT"
echo "capacity: $AGENT_CAPACITY"

cd "$REPO_DIR"

if ! command -v "$PYTHON_BIN" >/dev/null 2>&1; then
  echo "ERROR: Python not found: $PYTHON_BIN" >&2
  exit 1
fi

if [ ! -f "$REPO_DIR/pyproject.toml" ]; then
  echo "ERROR: not a CodeartsBridge checkout: $REPO_DIR" >&2
  exit 1
fi

CODEARTS_BIN="${CODEARTS_BIN:-$(command -v codearts || true)}"
if [ -z "$CODEARTS_BIN" ]; then
  for candidate in     "$RUN_HOME/.codeartsdoer/installers/bin/codearts"     "$RUN_HOME/.local/bin/codearts"     "$RUN_HOME/.codeartsdoer/installers/codearts"; do
    if [ -x "$candidate" ]; then
      CODEARTS_BIN="$candidate"
      break
    fi
  done
fi

if [ -z "$CODEARTS_BIN" ]; then
  echo "ERROR: CodeArts CLI not found. Install/configure CodeArts first." >&2
  exit 1
fi

if ! CODEARTS_VERSION_OUTPUT="$("$CODEARTS_BIN" --version 2>&1)"; then
  echo "ERROR: CodeArts CLI exists but '--version' failed: $CODEARTS_BIN" >&2
  exit 1
fi

echo "codearts: $CODEARTS_BIN"
CODEARTS_VERSION="$(printf '%s\n' "$CODEARTS_VERSION_OUTPUT" | grep -Eo '[0-9]+\.[0-9]+\.[0-9]+' | head -n 1 || true)"
if [ -z "$CODEARTS_VERSION" ]; then
  echo "ERROR: Could not parse CodeArts CLI version" >&2
  exit 1
fi
echo "version:  $CODEARTS_VERSION"
if [ -n "$EXPECTED_CODEARTS_VERSION" ] && [ "$CODEARTS_VERSION" != "$EXPECTED_CODEARTS_VERSION" ]; then
  echo "ERROR: CodeArts CLI version mismatch: expected $EXPECTED_CODEARTS_VERSION, got $CODEARTS_VERSION" >&2
  exit 1
fi

"$PYTHON_BIN" -m venv "$VENV_DIR"
"$VENV_DIR/bin/python" -m pip install --upgrade pip >/dev/null
"$VENV_DIR/bin/python" -m pip install -e "$REPO_DIR"
"$VENV_DIR/bin/python" -m bridge.agent.cli --help >/dev/null

mkdir -p "$AGENT_ROOT" "$CONFIG_DIR"

cat >"$CONFIG_DIR/agent.json" <<EOF
{
  "agentVersion": "0.1.0",
  "capacity": $AGENT_CAPACITY
}
EOF

ENV_FILE="$CONFIG_DIR/agent.env"
echo "codearts env: $CODEARTS_ENV_FILE (preserved, optional)"

case "$AUTH_MODE" in
  off)
    rm -f "$ENV_FILE"
    echo "auth: off (forced)"
    ;;
  token)
    if [ -z "${BRIDGE_AGENT_TOKEN:-}" ]; then
      echo "ERROR: BRIDGE_AGENT_AUTH=token requires BRIDGE_AGENT_TOKEN" >&2
      exit 1
    fi
    umask 077
    printf 'BRIDGE_AGENT_TOKEN=%s\n' "$BRIDGE_AGENT_TOKEN" >"$ENV_FILE"
    echo "auth: token (configured)"
    ;;
  auto)
    if [ -n "${BRIDGE_AGENT_TOKEN:-}" ]; then
      umask 077
      printf 'BRIDGE_AGENT_TOKEN=%s\n' "$BRIDGE_AGENT_TOKEN" >"$ENV_FILE"
      echo "auth: token (from BRIDGE_AGENT_TOKEN)"
    elif [ -f "$ENV_FILE" ]; then
      echo "auth: existing agent.env preserved"
    else
      echo "auth: off (trusted LAN default)"
    fi
    ;;
  *)
    echo "ERROR: BRIDGE_AGENT_AUTH must be auto, off, or token" >&2
    exit 1
    ;;
esac

AGENT_ENV_DIRECTIVE="EnvironmentFile=-$ENV_FILE"
AGENT_TOKEN_UNSET=""
if [ "$AUTH_MODE" = "off" ]; then
  # Keep trusted-LAN auth-off explicit in the generated unit. Otherwise an
  # agent.env created later would silently re-enable token auth while the
  # Bridge registry still has no matching token.
  AGENT_ENV_DIRECTIVE=""
  AGENT_TOKEN_UNSET="BRIDGE_AGENT_TOKEN "
fi

if [ "$BRIDGE_INSTALL_SYSTEMD" != "1" ]; then
  echo "systemd install skipped (BRIDGE_INSTALL_SYSTEMD=$BRIDGE_INSTALL_SYSTEMD)"
  echo "Run manually:"
  echo "  $VENV_DIR/bin/python -m bridge.agent.cli --listen 0.0.0.0 --port $AGENT_PORT --root $AGENT_ROOT --config $CONFIG_DIR/agent.json"
  exit 0
fi

UNIT_FILE="/etc/systemd/system/$SERVICE_NAME.service"
TMP_UNIT="$(mktemp)"
trap 'rm -f "$TMP_UNIT"' EXIT

cat >"$TMP_UNIT" <<EOF
[Unit]
Description=CodeartsBridge Worker Agent
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=$RUN_USER
WorkingDirectory=$REPO_DIR
Environment=PYTHONUNBUFFERED=1
Environment=HOME=$RUN_HOME
Environment=PATH=$RUN_HOME/.local/bin:$RUN_HOME/.codeartsdoer/installers/bin:$RUN_HOME/.codeartsdoer/installers:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/bin
Environment=CODEARTS_DISABLE_AUTO_UPDATE=$DISABLE_CODEARTS_AUTO_UPDATE
$AGENT_ENV_DIRECTIVE
EnvironmentFile=-$CODEARTS_ENV_FILE
UnsetEnvironment=${AGENT_TOKEN_UNSET}OPENCODE OPENCODE_CHANNEL OPENCODE_CONFIG OPENCODE_CONFIG_FILE OPENCODE_PID OPENCODE_SERVER_PASSWORD OPENCODE_SERVER_USERNAME OPENCODE_SKIP_MIGRATIONS
ExecStart=$VENV_DIR/bin/python -m bridge.agent.cli --listen 0.0.0.0 --port $AGENT_PORT --root $AGENT_ROOT --config $CONFIG_DIR/agent.json
Restart=always
RestartSec=2
KillMode=mixed

[Install]
WantedBy=multi-user.target
EOF

sudo cp "$TMP_UNIT" "$UNIT_FILE"
sudo systemctl daemon-reload
sudo systemctl enable "$SERVICE_NAME" >/dev/null
sudo systemctl restart "$SERVICE_NAME"

echo "Installed: $UNIT_FILE"
sudo systemctl --no-pager --full status "$SERVICE_NAME" || true

if command -v curl >/dev/null 2>&1; then
  sleep 1
  if curl -fsS "http://127.0.0.1:$AGENT_PORT/v1/health" >/dev/null; then
    echo "Health: OK"
  else
    echo "WARNING: Agent started but /v1/health is not reachable yet" >&2
  fi
fi

echo "=== Done ==="
echo "Logs: journalctl -u $SERVICE_NAME -f"
