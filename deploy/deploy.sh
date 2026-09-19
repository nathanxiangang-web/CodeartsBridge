#!/bin/bash
# Deploy CodeartsBridge to worker nodes
# Run this from the bridge host (e.g. 192.168.178.50)
set -euo pipefail

SSH_KEY="${SSH_KEY:-$HOME/.ssh/cloudsite_remote}"
SSH_OPTS="-i $SSH_KEY -o BatchMode=yes -o StrictHostKeyChecking=no -o ConnectTimeout=10"
TARGETS=("${@:-nathan@192.168.178.51 nathan@192.168.178.52 nathan@192.168.178.53}")
BRIDGE_DIR="/home/nathan/bridge-python"

echo "=== CodeartsBridge Deployment ==="
echo "SSH key: $SSH_KEY"
echo "Targets: ${TARGETS[*]}"
echo "Bridge dir: $BRIDGE_DIR"
echo ""

# Check SSH key
if [ ! -f "$SSH_KEY" ]; then
    echo "ERROR: SSH key not found: $SSH_KEY"
    echo "Set SSH_KEY env var to the correct path."
    exit 1
fi

# Package the code
echo "[1/4] Packaging code..."
SCRIPT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
TARBALL="/tmp/bridge-python-deploy.tar.gz"
tar czf "$TARBALL" \
    -C "$SCRIPT_DIR" \
    src/bridge/ \
    pyproject.toml \
    projects.json \
    workers.json \
    protocol/ \
    2>/dev/null
echo "  Package: $(du -h "$TARBALL" | cut -f1)"

for target in "${TARGETS[@]}"; do
    host=$(echo "$target" | cut -d@ -f2)
    echo ""
    echo "[2/4] Deploying to $target ..."

    # Test connection
    if ! ssh $SSH_OPTS "$target" "echo connected" >/dev/null 2>&1; then
        echo "  ERROR: Cannot connect to $target"
        continue
    fi
    echo "  Connection: OK"

    # Upload
    scp $SSH_OPTS "$TARBALL" "$target:/tmp/bridge-python-deploy.tar.gz" >/dev/null 2>&1
    echo "  Upload: OK"

    # Install
    ssh $SSH_OPTS "$target" bash -s << 'REMOTE_SCRIPT'
set -euo pipefail
BRIDGE_DIR="/home/nathan/bridge-python"

# Create directory
mkdir -p "$BRIDGE_DIR"
cd "$BRIDGE_DIR"

# Extract
tar xzf /tmp/bridge-python-deploy.tar.gz

# Install as package
pip3 install --user -e . 2>&1 | tail -3

# Verify
python3 -c "import bridge; print(f'bridge version: {bridge.__version__}')"

echo "  Install: OK"
REMOTE_SCRIPT

    echo "[3/4] Verifying $target ..."
    ssh $SSH_OPTS "$target" "cd $BRIDGE_DIR && PYTHONPATH=src python3 -m bridge.cli doctor" 2>&1 || true

    echo "[4/4] Agent service on $target ..."
    ssh $SSH_OPTS "$target" bash -s << 'REMOTE_SYSTEMD'
BRIDGE_DIR="/home/nathan/bridge-python"
cat > /tmp/bridge-worker-agent.service << EOF
[Unit]
Description=Bridge Worker Agent
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
ExecStart=/usr/bin/python3 -m bridge.agent.cli --listen 0.0.0.0 --port 8765
WorkingDirectory=$BRIDGE_DIR
Environment=PYTHONPATH=$BRIDGE_DIR/src
Environment=PATH=/home/nathan/.codeartsdoer/installers:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/bin
Restart=on-failure
RestartSec=5
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
EOF
echo "  Service file: /tmp/bridge-worker-agent.service"
echo "  Install with: sudo cp /tmp/bridge-worker-agent.service /etc/systemd/system/ && sudo systemctl daemon-reload && sudo systemctl enable --now bridge-worker-agent"
REMOTE_SYSTEMD

    echo "  Done: $target"
done

# Cleanup
rm -f "$TARBALL"

echo ""
echo "=== Deployment Complete ==="
echo "Next steps on each target:"
echo "  1. sudo cp /tmp/bridge-worker-agent.service /etc/systemd/system/"
echo "  2. sudo systemctl daemon-reload && sudo systemctl enable --now bridge-worker-agent"
echo "  3. sudo systemctl status bridge-worker-agent"
