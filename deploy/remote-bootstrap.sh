# AI生成
#!/bin/bash
cd /home/nathan/bridge-python
echo "=== Bootstrap ==="
PYTHONPATH=src python3 -m bridge.cli bootstrap 2>&1
echo "=== Test daemon once ==="
PYTHONPATH=src python3 -m bridge.daemon once 2>&1
echo "=== CLI status ==="
PYTHONPATH=src python3 -m bridge.cli status 2>&1
echo "=== Directory structure ==="
ls -la tasks/ 2>&1
ls -la runtime/ 2>&1
echo "=== DONE ==="