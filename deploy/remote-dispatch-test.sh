# AI生成
#!/bin/bash
cd /home/nathan/bridge-python
export PYTHONPATH=src

echo "=========================================="
echo "  Remote Dispatch Test to 3 Workers"
echo "=========================================="

echo ""
echo "=== 1. Project/Worker Config ==="
echo "--- projects.json (id, transport, sshHost) ---"
python3 -c "
import json
with open('projects.json') as f:
    for p in json.load(f):
        print(f\"  {p['id']:30s}  transport={p.get('transport','?'):15s}  host={p.get('sshHost', p.get('host','-'))}\")
"
echo ""
echo "--- workers.json (id, host, enabled, caps) ---"
python3 -c "
import json
with open('workers.json') as f:
    for w in json.load(f):
        print(f\"  {w['id']:15s}  host={w.get('host','-'):30s}  enabled={w.get('enabled')}  caps={w.get('capabilities',[])}  transport={w.get('transport','-')}\")
"

echo ""
echo "=== 2. Create tasks for 3 remote workers ==="

# Find projects for each remote host
echo "Creating tasks for bus-rc1-w01 (178.52), bus-rc1-w03 (5.15), bus-rc1-w04 (178.51)..."

# Task for w01 (178.52 - tasking/scheduling)
cat > /tmp/task-w01.md << 'EOF'
# Objective
Remote dispatch test: verify bridge can dispatch to 178.52 (w01)

# Current Situation
Bridge Python v0.1 deployed on 178.50. Testing remote dispatch to w01 on 178.52.

# Required Changes
- Echo "hello from w01" and create a test marker file

# Acceptance Criteria
- Command executes successfully on 178.52
- RESULT.md generated in outbox

# Constraints
- This is a connectivity test only
- Do not modify any production files

# Deliverables
- RESULT.md with execution confirmation
- TESTS.md with pass status
EOF

# Task for w03 (5.15 - identity/workers/telemetry)
cat > /tmp/task-w03.md << 'EOF'
# Objective
Remote dispatch test: verify bridge can dispatch to 5.15 (w03)

# Current Situation
Bridge Python v0.1 deployed on 178.50. Testing remote dispatch to w03 on 5.15.

# Required Changes
- Echo "hello from w03" and verify environment

# Acceptance Criteria
- Command executes successfully on 5.15
- RESULT.md generated in outbox

# Constraints
- This is a connectivity test only

# Deliverables
- RESULT.md with execution confirmation
- TESTS.md with pass status
EOF

# Task for w04 (178.51 - review/QA)
cat > /tmp/task-w04.md << 'EOF'
# Objective
Remote dispatch test: verify bridge can dispatch to 178.51 (w04)

# Current Situation
Bridge Python v0.1 deployed on 178.50. Testing remote dispatch to w04 on 178.51.

# Required Changes
- Echo "hello from w04" and verify environment

# Acceptance Criteria
- Command executes successfully on 178.51
- RESULT.md generated in outbox

# Constraints
- This is a connectivity test only
- w04 is QA-only (no implement)

# Deliverables
- RESULT.md with execution confirmation
- TESTS.md with pass status
EOF

python3 -m bridge.cli create -p bus-rc1-w01 -t remote-test-w01 --task-file /tmp/task-w01.md --workspace-mode existing 2>&1
python3 -m bridge.cli create -p bus-rc1-w03 -t remote-test-w03 --task-file /tmp/task-w03.md --workspace-mode existing 2>&1
python3 -m bridge.cli create -p bus-rc1-w04 -t remote-test-w04 --task-file /tmp/task-w04.md --workspace-mode existing --role review 2>&1

echo ""
echo "=== 3. Status before dispatch ==="
python3 -m bridge.cli status 2>&1

echo ""
echo "=== 4. Dispatch (dry-run) ==="
python3 -m bridge.cli dispatch --dry-run 2>&1

echo ""
echo "=== 5. Real dispatch ==="
python3 -m bridge.cli dispatch 2>&1
echo "Exit code: $?"

echo ""
echo "=== 6. Status after dispatch ==="
python3 -m bridge.cli status 2>&1

echo ""
echo "=== 7. Check task states ==="
for t in remote-test-w01 remote-test-w03 remote-test-w04; do
    echo "--- $t ---"
    cat tasks/$t/state.json 2>&1
    echo ""
done

echo ""
echo "=== 8. Wait 10s and check again ==="
sleep 10
python3 -m bridge.cli status 2>&1

echo ""
echo "=== 9. Check task states after wait ==="
for t in remote-test-w01 remote-test-w03 remote-test-w04; do
    echo "--- $t ---"
    cat tasks/$t/state.json 2>&1
    echo ""
done

echo ""
echo "=== 10. Daemon once ==="
python3 -m bridge.daemon once 2>&1
echo "Exit code: $?"

echo ""
echo "=== 11. Final status ==="
python3 -m bridge.cli status 2>&1

echo ""
echo "=== 12. Check logs ==="
ls -la runtime/logs/ 2>&1
ls -la runtime/logs/dispatcher/ 2>&1

echo ""
echo "=== 13. Cleanup ==="
rm -rf tasks/remote-test-w01 tasks/remote-test-w03 tasks/remote-test-w04 /tmp/task-w01.md /tmp/task-w03.md /tmp/task-w04.md
echo "Cleaned up"

echo ""
echo "=========================================="
echo "  Remote Dispatch Test Complete"
echo "=========================================="