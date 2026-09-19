"""Playwright config for browser E2E tests (UI-07).

Playwright is a dev/test dependency only, not part of Bridge production runtime.
"""
import sys
from pathlib import Path

# Ensure src is on path for any bridge imports needed by tests
src = Path(__file__).resolve().parent.parent / "src"
if str(src) not in sys.path:
    sys.path.insert(0, str(src))