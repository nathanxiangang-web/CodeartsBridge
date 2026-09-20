#!/usr/bin/env python3
"""Audit and repair the CodeArts runtime used by a Worker Agent."""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import stat
import subprocess
import sys
import tempfile
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


WRITE_PERMISSIONS = (
    "edit",
    "write",
    "external_directory_write",
    "dotfile",
)
AKSK_NAMES = ("CODEARTS_CLI_AK", "CODEARTS_CLI_SK")
STALE_ENV_PREFIX = "OPENCODE"
VERSION_RE = re.compile(r"\b\d+\.\d+\.\d+\b")


def parse_debug_paths(output: str) -> dict[str, str]:
    paths: dict[str, str] = {}
    for raw_line in output.splitlines():
        parts = raw_line.strip().split(maxsplit=1)
        if len(parts) == 2:
            paths[parts[0]] = parts[1]
    return paths


def resolve_codearts(explicit: str | None, home: Path) -> Path:
    candidates: list[Path] = []
    if explicit:
        candidates.append(Path(explicit).expanduser())
    candidates.extend(
        (
            home / ".codeartsdoer/installers/bin/codearts",
            home / ".local/bin/codearts",
            home / ".codeartsdoer/installers/codearts",
        )
    )
    discovered = shutil.which("codearts")
    if discovered:
        candidates.append(Path(discovered))

    for candidate in candidates:
        if candidate.is_file() and os.access(candidate, os.X_OK):
            return candidate
    raise RuntimeError("CodeArts CLI executable was not found")


def run_codearts(codearts: Path, *args: str) -> str:
    result = subprocess.run(
        [str(codearts), *args],
        check=False,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        timeout=30,
    )
    if result.returncode != 0:
        detail = result.stdout.strip().splitlines()
        summary = detail[-1] if detail else f"exit {result.returncode}"
        raise RuntimeError(f"codearts {' '.join(args)} failed: {summary}")
    return result.stdout


def extract_version(output: str) -> str:
    match = VERSION_RE.search(output)
    if not match:
        raise RuntimeError("Could not parse CodeArts CLI version")
    return match.group(0)


def resolve_data_dir(codearts: Path, explicit: str | None) -> Path:
    if explicit:
        return Path(explicit).expanduser()
    paths = parse_debug_paths(run_codearts(codearts, "debug", "paths"))
    if "data" not in paths:
        raise RuntimeError("codearts debug paths did not return a data directory")
    return Path(paths["data"])


def load_permission_rules(path: Path) -> list[dict[str, Any]]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, list) or not all(isinstance(item, dict) for item in data):
        raise RuntimeError(f"Permission file is not a JSON rule list: {path}")
    return data


def permission_action(rules: list[dict[str, Any]], name: str) -> str | None:
    action = None
    for rule in rules:
        if rule.get("permission") == name and rule.get("pattern", "*") == "*":
            action = str(rule.get("action", "")) or None
    return action


def allow_write_permissions(
    rules: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[str]]:
    updated = [dict(rule) for rule in rules]
    changed: list[str] = []
    for name in WRITE_PERMISSIONS:
        matches = [
            rule
            for rule in updated
            if rule.get("permission") == name and rule.get("pattern", "*") == "*"
        ]
        if not matches:
            updated.append({"permission": name, "pattern": "*", "action": "allow"})
            changed.append(name)
            continue
        if any(rule.get("action") != "allow" for rule in matches):
            for rule in matches:
                rule["action"] = "allow"
            changed.append(name)
    return updated, changed


def process_environ(pid: int, proc_root: Path = Path("/proc")) -> dict[str, str]:
    raw = (proc_root / str(pid) / "environ").read_bytes().split(b"\0")
    environ: dict[str, str] = {}
    for item in raw:
        if b"=" not in item:
            continue
        key, value = item.split(b"=", 1)
        environ[key.decode(errors="replace")] = value.decode(errors="replace")
    return environ


def find_agent_pids(proc_root: Path = Path("/proc")) -> list[int]:
    pids: list[int] = []
    for entry in proc_root.iterdir():
        if not entry.name.isdigit():
            continue
        try:
            cmdline = (entry / "cmdline").read_bytes().replace(b"\0", b" ")
        except (FileNotFoundError, PermissionError, ProcessLookupError):
            continue
        if b"bridge.agent.cli" in cmdline and b"python" in cmdline:
            pids.append(int(entry.name))
    return sorted(pids)


def stale_opencode_names(environ: dict[str, str]) -> list[str]:
    return sorted(name for name in environ if name.startswith(STALE_ENV_PREFIX))


def health(port: int) -> dict[str, Any]:
    with urllib.request.urlopen(
        f"http://127.0.0.1:{port}/v1/health", timeout=5
    ) as response:
        data = json.loads(response.read().decode("utf-8"))
    if not isinstance(data, dict):
        raise RuntimeError("Agent health response is not a JSON object")
    return data


class Audit:
    def __init__(self) -> None:
        self.failures = 0

    def pass_(self, key: str, value: str) -> None:
        print(f"PASS {key}={value}")

    def fail(self, key: str, value: str) -> None:
        self.failures += 1
        print(f"FAIL {key}={value}")


def audit(args: argparse.Namespace) -> int:
    report = Audit()
    home = Path(args.home).expanduser()
    try:
        codearts = resolve_codearts(args.codearts_bin, home)
        version = extract_version(run_codearts(codearts, "--version"))
        if args.expected_version and version != args.expected_version:
            report.fail("version", f"expected:{args.expected_version},actual:{version}")
        else:
            report.pass_("version", version)

        data_dir = resolve_data_dir(codearts, args.data_dir)
        report.pass_("data_dir", str(data_dir))
        permission_file = data_dir / "storage/permission/global.json"
        rules = load_permission_rules(permission_file)
        report.pass_("permission_file", str(permission_file))
        for name in WRITE_PERMISSIONS:
            action = permission_action(rules, name)
            if action == "allow":
                report.pass_(f"permission.{name}", action)
            else:
                report.fail(f"permission.{name}", action or "missing")
    except Exception as exc:
        report.fail("runtime", str(exc))

    if not args.skip_agent:
        try:
            pids = [args.agent_pid] if args.agent_pid else find_agent_pids()
            if not pids:
                raise RuntimeError("Worker Agent process was not found")
            if len(pids) > 1:
                report.fail("agent_processes", ",".join(str(pid) for pid in pids))
            pid = pids[-1]
            environ = process_environ(pid)
            report.pass_("agent_pid", str(pid))

            stale = stale_opencode_names(environ)
            if stale:
                report.fail("stale_opencode_env", ",".join(stale))
            else:
                report.pass_("stale_opencode_env", "none")

            auto_update = environ.get("CODEARTS_DISABLE_AUTO_UPDATE", "")
            if auto_update.lower() == "true":
                report.pass_("auto_update", "disabled")
            else:
                report.fail("auto_update", "not_disabled")

            if args.require_aksk:
                missing = [name for name in AKSK_NAMES if not environ.get(name)]
                if missing:
                    report.fail("agent_aksk", "missing:" + ",".join(missing))
                else:
                    report.pass_("agent_aksk", "present")
        except Exception as exc:
            report.fail("agent", str(exc))

        if not args.skip_health:
            try:
                health_data = health(args.agent_port)
                if health_data.get("ok") is True:
                    report.pass_("agent_health", "ok")
                else:
                    report.fail("agent_health", "not_ok")
            except Exception as exc:
                report.fail("agent_health", str(exc))

    print("RESULT " + ("PASS" if report.failures == 0 else "FAIL"))
    return 0 if report.failures == 0 else 1


def fix_permissions(args: argparse.Namespace) -> int:
    home = Path(args.home).expanduser()
    codearts = resolve_codearts(args.codearts_bin, home)
    data_dir = resolve_data_dir(codearts, args.data_dir)
    permission_file = data_dir / "storage/permission/global.json"
    rules = load_permission_rules(permission_file)
    updated, changed = allow_write_permissions(rules)

    print(f"permission_file={permission_file}")
    print("changes=" + (",".join(changed) if changed else "none"))
    if not changed:
        return 0
    if not args.apply:
        print("dry_run=true")
        print("Re-run with --apply to create a backup and update the file.")
        return 0

    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    backup = permission_file.with_name(
        f"{permission_file.name}.before-codeartsbridge-write-fix-{stamp}"
    )
    shutil.copy2(permission_file, backup)
    original_mode = stat.S_IMODE(permission_file.stat().st_mode)
    payload = json.dumps(updated, indent=2, ensure_ascii=True) + "\n"
    with tempfile.NamedTemporaryFile(
        mode="w",
        encoding="utf-8",
        dir=permission_file.parent,
        prefix=f".{permission_file.name}.",
        delete=False,
    ) as handle:
        handle.write(payload)
        temporary = Path(handle.name)
    os.chmod(temporary, original_mode)
    os.replace(temporary, permission_file)
    print(f"backup={backup}")
    print("applied=true")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--home", default=str(Path.home()))
    common.add_argument("--codearts-bin")
    common.add_argument("--data-dir")

    audit_parser = subparsers.add_parser("audit", parents=[common])
    audit_parser.add_argument(
        "--expected-version", default=os.environ.get("CODEARTS_EXPECTED_VERSION", "")
    )
    audit_parser.add_argument("--agent-port", type=int, default=8765)
    audit_parser.add_argument("--agent-pid", type=int)
    audit_parser.add_argument("--require-aksk", action="store_true")
    audit_parser.add_argument("--skip-agent", action="store_true")
    audit_parser.add_argument("--skip-health", action="store_true")
    audit_parser.set_defaults(func=audit)

    fix_parser = subparsers.add_parser("fix-permissions", parents=[common])
    fix_parser.add_argument("--apply", action="store_true")
    fix_parser.set_defaults(func=fix_permissions)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    return int(args.func(args))


if __name__ == "__main__":
    sys.exit(main())
