"""CLI contract regression: every command in --help must have a real handler.

Guards against dead entry points left behind by module deletions
(e.g. adaptive-dispatch, cost, bridge-daemon).
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))


DEAD_COMMANDS = {"adaptive-dispatch", "cost", "bridge-daemon"}


def test_help_exits_zero():
    rc = subprocess.call(
        [sys.executable, "-m", "bridge.cli", "--help"],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        env={"PYTHONPATH": str(Path(__file__).resolve().parents[1] / "src"), "PATH": "/usr/bin:/bin"},
    )
    assert rc == 0


def test_no_dead_commands_in_help():
    from bridge.cli import build_parser, COMMAND_MAP
    parser = build_parser()
    available = set(COMMAND_MAP.keys())
    for dead in DEAD_COMMANDS:
        assert dead not in available, f"dead command '{dead}' still in COMMAND_MAP"
        for action in parser._actions:
            if hasattr(action, "choices") and action.choices:
                assert dead not in action.choices, f"dead command '{dead}' still in parser choices"


def test_all_commands_have_real_handlers():
    from bridge.cli import COMMAND_MAP
    for cmd, handler in COMMAND_MAP.items():
        assert callable(handler), f"command '{cmd}' maps to non-callable {handler}"


def test_no_bridge_daemon_entry_point():
    import tomllib
    pyproject = Path(__file__).resolve().parents[1] / "pyproject.toml"
    with open(pyproject, "rb") as f:
        data = tomllib.load(f)
    scripts = data.get("project", {}).get("scripts", {})
    assert "bridge-daemon" not in scripts, "bridge-daemon entry point must be deleted"
    assert "bridge" in scripts, "bridge entry point must exist"