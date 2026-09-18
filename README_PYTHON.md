# CodeartsBridge

Python-native bridge between Codex architects and GLM workers. Manages task dispatch, worker execution, transport, and review across multiple remote Linux hosts.

## What This Is

A file-based communication bridge that lets an architect (Codex/agent) create engineering tasks, dispatch them to GLM workers running CodeArts CLI on remote machines, and review results — without any direct coupling between the architect and worker processes.

- **Zero third-party dependencies** — Python 3.10+ standard library only
- **Linux-native** — runs as a systemd service, no PowerShell required
- **Protocol-preserving** — same task directory structure, state machine, and config format as the original PowerShell bridge
- **Four transports** — local, ssh-shell, ssh, remote-worktree

## Architecture

```
Architect ──inbox──▶ Bridge Daemon ──dispatch──▶ Worker (CodeArts CLI)
         ◀─outbox──                ◀─result────
```

```
src/bridge/
├─ atomic.py          Atomic file writes (.tmp + os.replace)
├─ locks.py           File locks (fcntl on Linux, msvcrt on Windows)
├─ config.py          Project/Worker config loading from JSON
├─ state.py           State machine (READY→QUEUED→...→DONE)
├─ codearts.py        CodeArts CLI wrapper (prompt, args, JSONL parse)
├─ git_ops.py         Git operations (bundle export/import, guardrails)
├─ task.py            Task lifecycle (create, review, instructions)
├─ dispatch.py        Dispatch planning (worker match, concurrency, workspace)
├─ worker.py          Worker process management (transport, state, telemetry)
├─ cli.py             CLI entry point (11 subcommands)
├─ daemon.py          Daemon (poll loop, health, signal handling)
├─ progress.py        Progress display (show-progress, watch-tasks)
├─ transport/         Four transport implementations
│  ├─ local.py        Local CLI execution
│  ├─ ssh.py          Remote CLI + scp file transfer
│  ├─ ssh_shell.py    Local CLI + remote project path
│  └─ remote_worktree.py  Per-task isolated repo via git bundle
└─ policy/            Policy/profile engine
   ├─ engine.py       Profile loading, validation, phase/check selection
   ├─ runtime.py      Check execution, evidence verification, approval gates
   └─ timeout.py      Soft/hard timeout management
```

## Quick Start

```bash
# Install
git clone https://github.com/nathanxiangang-web/CodeartsBridge.git
cd CodeartsBridge
export PYTHONPATH=src

# Initialize
python3 -m bridge.cli bootstrap
python3 -m bridge.cli doctor

# Create a task
python3 -m bridge.cli create --project my-project --task my-task --objective "Fix the bug" --changes "Update handler" --acceptance "Tests pass"

# Dispatch to workers
python3 -m bridge.cli dispatch

# Review results
python3 -m bridge.cli status
python3 -m bridge.cli review-pass --task my-task
```

## CLI Commands

| Command | Description |
|---------|-------------|
| `bootstrap` | Initialize directory structure |
| `doctor` | Check environment (Python, SSH, CodeArts CLI, config) |
| `status` | Show task status summary |
| `create` | Create a new task |
| `dispatch` | Dispatch ready tasks to workers |
| `run` | Run a single task (used by dispatcher) |
| `review-pass` | Mark task review as PASS |
| `review-fix` | Mark task review as FIX with instructions |
| `cancel` | Cancel a running task |
| `pause` | Pause a task |
| `resume` | Resume a paused task |

## Daemon

```bash
# Run as systemd service
sudo cp deploy/bridge-daemon.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now bridge-daemon

# Or run manually
PYTHONPATH=src python3 -m bridge.daemon run

# Single dispatch cycle
PYTHONPATH=src python3 -m bridge.daemon once
```

## Configuration

### projects.json

```json
[
  {
    "id": "my-project",
    "transport": "ssh",
    "projectRoot": "/home/nathan/myproject",
    "sshHost": "nathan@192.168.1.10",
    "remoteBridgeRoot": "/home/nathan/.codex-glm-bridge",
    "remoteCliPath": "/home/nathan/.codeartsdoer/installers/bin/codearts"
  }
]
```

### workers.json

```json
[
  {
    "id": "w01",
    "host": "nathan@192.168.1.10",
    "cliPath": "/home/nathan/.codeartsdoer/installers/bin/codearts",
    "model": "huaweicloud-maas/GLM-5.2",
    "capabilities": ["implement", "review", "test"],
    "concurrencyLimit": 1,
    "enabled": true
  }
]
```

## State Machine

```
READY → QUEUED → STARTING → RUNNING → REVIEW_REQUIRED → DONE
                                  │                      ▲
                                  ├→ BLOCKED             │
                                  ├→ ASSISTANCE_REQUIRED │
                                  ├→ AUTH_REQUIRED       │
                                  ├→ RETRYABLE           │
                                  └→ FAILED             │
REVIEW_REQUIRED → FIX_REQUIRED → RUNNING
```

## Transports

| Transport | CLI Location | Project Location | Use Case |
|-----------|-------------|-----------------|----------|
| `local` | Local | Local | Same-machine development |
| `ssh-shell` | Local | Remote | Local CLI, remote project via SSH |
| `ssh` | Remote | Remote | Full remote execution |
| `remote-worktree` | Remote | Per-task isolated repo | Parallel development with isolation |

## Policy Engine

JSON-based profiles define phases, checks, and approval gates per project. No project-specific logic hardcoded — the engine is project-agnostic.

```json
{
  "profileId": "my-profile",
  "projectId": "my-project",
  "phases": [
    {
      "id": "build",
      "roles": ["implement"],
      "checks": [
        {
          "id": "unit-tests",
          "command": {"executable": "python3", "argv": ["-m", "pytest"]},
          "expectExitCode": 0
        }
      ]
    }
  ]
}
```

## Testing

```bash
PYTHONPATH=src python3 -m pytest tests/ -v
```

67 tests covering atomic I/O, locks, config, state machine, transports, dispatch, CLI, policy engine, and timeout.

## Protocol

See `protocol/` directory for the full bridge protocol specification:
- `PROTOCOL.md` — State machine, task directory, file ownership
- `ARCHITECT.md` — Architect contract (task format, review)
- `WORKER.md` — Worker contract (execution, blockers, timeouts)
- `PROFILE.md` — Policy/profile engine contract

## Version

v0.1 — Python rewrite of the PowerShell bridge (4715 lines → 15 modules)

## License

Private. Internal use only.