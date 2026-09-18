# AI生成
#!/bin/bash
cd /home/nathan/bridge-python

echo "=== Create systemd service ==="
cat > /tmp/bridge-daemon.service << 'EOF'
[Unit]
Description=Codex-GLM Bridge Daemon (Python)
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
Environment=PYTHONPATH=/home/nathan/bridge-python/src
Environment=BRIDGE_ROOT=/home/nathan/bridge-python
ExecStart=/usr/bin/python3 -m bridge.daemon run
WorkingDirectory=/home/nathan/bridge-python
Restart=on-failure
RestartSec=5
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
EOF
echo "Service file created at /tmp/bridge-daemon.service"
cat /tmp/bridge-daemon.service

echo "=== Test daemon once ==="
PYTHONPATH=src python3 -m bridge.daemon once 2>&1

echo "=== Test CLI status ==="
PYTHONPATH=src python3 -m bridge.cli status 2>&1

echo "=== SETUP_DONE ==="