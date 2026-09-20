"""CLI/packaging contract regression.

Guards against dead entry points left behind by module deletions and keeps the
two supported executables importable:
- bridge
- bridge-worker-agent
"""
from __future__ import annotations

import importlib
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))


DEAD_COMMANDS = {"adaptive-dispatch", "cost", "bridge-daemon"}


def _project_scripts() -> dict[str, str]:
    import tomllib

    pyproject = Path(__file__).resolve().parents[1] / "pyproject.toml"
    with open(pyproject, "rb") as f:
        data = tomllib.load(f)
    return data.get("project", {}).get("scripts", {})


def test_help_exits_zero():
    rc = subprocess.call(
        [sys.executable, "-m", "bridge.cli", "--help"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        env={
            "PYTHONPATH": str(Path(__file__).resolve().parents[1] / "src"),
            "PATH": "/usr/bin:/bin",
        },
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
                assert dead not in action.choices, (
                    f"dead command '{dead}' still in parser choices"
                )


def test_all_commands_have_real_handlers():
    from bridge.cli import COMMAND_MAP

    for cmd, handler in COMMAND_MAP.items():
        assert callable(handler), f"command '{cmd}' maps to non-callable {handler}"


def test_supported_console_scripts_exist_and_import():
    scripts = _project_scripts()

    assert "bridge-daemon" not in scripts, "bridge-daemon entry point must stay deleted"
    assert scripts.get("bridge") == "bridge.cli:main"
    assert scripts.get("bridge-worker-agent") == "bridge.agent.cli:main"

    for name in ("bridge", "bridge-worker-agent"):
        module_name, attr = scripts[name].split(":", 1)
        module = importlib.import_module(module_name)
        assert callable(getattr(module, attr))


def test_worker_agent_module_help_exits_zero():
    rc = subprocess.call(
        [sys.executable, "-m", "bridge.agent.cli", "--help"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        env={
            "PYTHONPATH": str(Path(__file__).resolve().parents[1] / "src"),
            "PATH": "/usr/bin:/bin",
        },
    )
    assert rc == 0
