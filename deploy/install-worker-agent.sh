#!/bin/bash
set -euo pipefail

AGENT_ROOT="${1:-$HOME/.codex-glm-bridge/agent}"
CONFIG_DIR="$HOME/.config/codeartsbridge"
SERVICE_FILE="bridge-worker-agent.service"
REPO_DIR="${BRIDGE_REPO:-$HOME/bridge-python}"

echo "=== Bridge Worker Agent Installer ==="

mkdir -p "$AGENT_ROOT" "$CONFIG_DIR"

if [ ! -f "$CONFIG_DIR/agent.json" ]; then
    cat > "$CONFIG_DIR/agent.json" << EOF
{
  "agentVersion": "0.1.0",
  "capacity": 1,
  "allowedRoots": ["$REPO_DIR"]
}
EOF
    echo "Created $CONFIG_DIR/agent.json"
fi

if [ ! -f "$CONFIG_DIR/agent.env" ]; then
    TOKEN=$(python3 -c "import secrets; print(secrets.token_urlsafe(32))")
    cat > "$CONFIG_DIR/agent.env" << EOF
BRIDGE_AGENT_TOKEN=$TOKEN
EOF
    chmod 600 "$CONFIG_DIR/agent.env"
    echo "Created $CONFIG_DIR/agent.env with generated token"
    echo "Token: $TOKEN"
fi

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
if [ -f "$SCRIPT_DIR/$SERVICE_FILE" ]; then
    sudo cp "$SCRIPT_DIR/$SERVICE_FILE" /etc/systemd/system/
    sudo systemctl daemon-reload
    sudo systemctl enable bridge-worker-agent
    echo "Service installed and enabled"
fi

echo "=== Done ==="
echo "Start with: sudo systemctl start bridge-worker-agent"

echo "Check with: sudo systemctl status bridge-worker-agent"