# AI生成
#!/bin/bash
cd /home/nathan/bridge-python
export PYTHONPATH=src

echo "=========================================="
echo "  CodeartsBridge Functional Tests on 178.50"
echo "=========================================="

echo ""
echo "=== 1. Doctor Check ==="
python3 -m bridge.cli doctor 2>&1

echo ""
echo "=== 2. Bootstrap ==="
python3 -m bridge.cli bootstrap 2>&1

echo ""
echo "=== 3. Status (empty) ==="
python3 -m bridge.cli status 2>&1

echo ""
echo "=== 4. Create task file ==="
cat > /tmp/test-task.md << 'TASKEOF'
# Objective
Functional test: verify bridge task lifecycle

# Required Changes
- Create a test file

# Acceptance Criteria
- Test file exists
TASKEOF
echo "Task file created"

echo ""
echo "=== 5. Create Task ==="
python3 -m bridge.cli create -p selftest -t func-test-001 --task-file /tmp/test-task.md 2>&1
echo "Exit code: $?"

echo ""
echo "=== 6. Verify task directory ==="
ls -la tasks/func-test-001/ 2>&1
echo "--- META.json ---"
cat tasks/func-test-001/META.json 2>&1
echo ""
echo "--- state.json ---"
cat tasks/func-test-001/state.json 2>&1
echo ""
echo "--- inbox ---"
ls -la tasks/func-test-001/inbox/ 2>&1
cat tasks/func-test-001/inbox/001-TASK.md 2>&1

echo ""
echo "=== 7. Status (with task) ==="
python3 -m bridge.cli status 2>&1

echo ""
echo "=== 8. Dispatch ==="
python3 -m bridge.cli dispatch 2>&1
echo "Exit code: $?"

echo ""
echo "=== 9. Check state after dispatch ==="
cat tasks/func-test-001/state.json 2>&1

echo ""
echo "=== 10. Simulate worker completion ==="
mkdir -p tasks/func-test-001/outbox
cat > tasks/func-test-001/outbox/RESULT.md << 'EOF'
# Result
Created test file successfully.
EOF
cat > tasks/func-test-001/outbox/TESTS.md << 'EOF'
# Tests
All tests passed.
EOF
cat > tasks/func-test-001/outbox/DIFF.stat << 'EOF'
1 file changed, 1 insertion(+)
EOF
echo "Outbox files created"

echo ""
echo "=== 11. Review Pass ==="
python3 -m bridge.cli review-pass -t func-test-001 2>&1
echo "Exit code: $?"

echo ""
echo "=== 12. Final state ==="
cat tasks/func-test-001/state.json 2>&1

echo ""
echo "=== 13. Daemon single cycle ==="
python3 -m bridge.daemon once 2>&1
echo "Exit code: $?"

echo ""
echo "=== 14. Create second task ==="
python3 -m bridge.cli create -p selftest -t func-test-002 --task-file /tmp/test-task.md 2>&1
echo "Exit code: $?"

echo ""
echo "=== 15. Review Fix ==="
cat > /tmp/test-fix.md << 'FIXEOF'
Fix the formatting issue in the output file.
FIXEOF
python3 -m bridge.cli review-fix -t func-test-002 --fix-file /tmp/test-fix.md 2>&1
echo "Exit code: $?"

echo ""
echo "=== 16. Verify FIX in inbox ==="
ls -la tasks/func-test-002/inbox/ 2>&1
cat tasks/func-test-002/inbox/002-FIX.md 2>&1

echo ""
echo "=== 17. Check state (should be FIX_REQUIRED) ==="
cat tasks/func-test-002/state.json 2>&1

echo ""
echo "=== 18. Cancel task ==="
python3 -m bridge.cli cancel -t func-test-002 2>&1
cat tasks/func-test-002/state.json 2>&1

echo ""
echo "=== 19. Unit tests ==="
python3 -m pytest tests/ -q 2>&1

echo ""
echo "=== 20. Cleanup ==="
rm -rf tasks/func-test-001 tasks/func-test-002 /tmp/test-task.md /tmp/test-fix.md
echo "Cleaned up"

echo ""
echo "=========================================="
echo "  Functional Tests Complete"
echo "=========================================="