# AI生成
#!/bin/bash
cd /home/nathan/bridge-python
echo "=== Install package ==="
python3 -m pip install --user -e . 2>&1 | tail -5
echo "=== Verify import ==="
PYTHONPATH=src python3 -c "import bridge; print('bridge version:', bridge.__version__)"
echo "=== Run tests ==="
PYTHONPATH=src python3 -m pytest tests/ -v 2>&1 | tail -30
echo "=== Doctor check ==="
PYTHONPATH=src python3 -m bridge.cli doctor 2>&1
echo "=== DEPLOY_DONE ==="