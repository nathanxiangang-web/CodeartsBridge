from __future__ import annotations

import importlib.util
from pathlib import Path


MODULE_PATH = Path(__file__).parents[1] / "deploy" / "codearts-worker-runtime.py"
SPEC = importlib.util.spec_from_file_location("codearts_worker_runtime", MODULE_PATH)
assert SPEC and SPEC.loader
runtime = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(runtime)


def test_parse_debug_paths_uses_reported_data_directory():
    paths = runtime.parse_debug_paths(
        "home       /home/nathan\n"
        "data       /home/nathan/.local/share/opencode\n"
        "config     /home/nathan/.config/opencode\n"
    )

    assert paths["data"] == "/home/nathan/.local/share/opencode"


def test_allow_write_permissions_updates_and_appends_without_losing_rules():
    rules = [
        {"permission": "browser", "pattern": "*", "action": "ask"},
        {"permission": "edit", "pattern": "*", "action": "ask"},
        {"permission": "write", "pattern": "*", "action": "allow"},
        {
            "permission": "external_directory_write",
            "pattern": "*",
            "action": "ask",
        },
    ]

    updated, changed = runtime.allow_write_permissions(rules)

    assert set(changed) == {"edit", "external_directory_write", "dotfile"}
    assert runtime.permission_action(updated, "edit") == "allow"
    assert runtime.permission_action(updated, "write") == "allow"
    assert runtime.permission_action(updated, "external_directory_write") == "allow"
    assert runtime.permission_action(updated, "dotfile") == "allow"
    assert updated[0] == rules[0]
    assert rules[1]["action"] == "ask"


def test_stale_opencode_names_never_return_values():
    environ = {
        "CODEARTS_CLI_AK": "secret-ak",
        "CODEARTS_CLI_SK": "secret-sk",
        "OPENCODE_CONFIG": "/old/config.json",
        "OPENCODE_SERVER_PASSWORD": "secret-password",
    }

    assert runtime.stale_opencode_names(environ) == [
        "OPENCODE_CONFIG",
        "OPENCODE_SERVER_PASSWORD",
    ]
