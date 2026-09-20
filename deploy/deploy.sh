#!/usr/bin/env bash
# Optional batch-upgrade helper for Worker hosts.
# Canonical single-node installer is deploy/install-worker-agent.sh.
set -euo pipefail

REMOTE_REPO="${BRIDGE_REMOTE_REPO:-/home/nathan/bridge-python}"
SSH_KEY="${SSH_KEY:-}"
SSH_USER="${BRIDGE_SSH_USER:-nathan}"

if [ "$#" -eq 0 ]; then
  if [ -z "${BRIDGE_WORKER_HOSTS:-}" ]; then
    cat <<EOF
Usage:
  $0 192.168.178.51 192.168.178.52 192.168.178.53

or:
  BRIDGE_WORKER_HOSTS="192.168.178.51 192.168.178.52 192.168.178.53" $0

Optional:
  SSH_KEY=/path/to/key
  BRIDGE_SSH_USER=nathan
  BRIDGE_REMOTE_REPO=/home/nathan/bridge-python
EOF
    exit 2
  fi
  # Intentional word splitting: hosts are supplied as a space-separated list.
  # shellcheck disable=SC2206
  TARGETS=(${BRIDGE_WORKER_HOSTS})
else
  TARGETS=("$@")
fi

SSH_ARGS=(-o BatchMode=yes -o ConnectTimeout=10)
if [ -n "$SSH_KEY" ]; then
  SSH_ARGS+=(-i "$SSH_KEY")
fi

echo "=== CodeartsBridge Worker Batch Upgrade ==="
echo "remote repo: $REMOTE_REPO"
echo "targets:     ${TARGETS[*]}"

for host in "${TARGETS[@]}"; do
  target="$SSH_USER@$host"
  echo
  echo "[$target] updating..."

  ssh "${SSH_ARGS[@]}" "$target" bash -s -- "$REMOTE_REPO" <<'REMOTE'
set -euo pipefail
REPO_DIR="$1"
cd "$REPO_DIR"

git fetch origin
git checkout main
git pull --ff-only origin main

./deploy/install-worker-agent.sh
REMOTE

  echo "[$target] OK"
done

echo
echo "=== Done ==="
echo "If the bridge host is also a Worker, run ./deploy/install-worker-agent.sh locally there."
