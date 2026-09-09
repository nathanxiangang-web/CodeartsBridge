# Bridge Daemon Production Layout

This document describes a future production layout for the codex-glm Bridge
supervisor under `C:\ProgramData\CodexGLMBridge`. The supervisor scripts
created in this task are safe to install later as a Windows service or
scheduled service account, but this task does NOT install anything.

## Directory separation

```
C:/ProgramData/CodexGLMBridge/
    config\
        bridge.json          # registry, defaults, project list
        daemon.json          # supervisor config (interval, maxWorkers, backoff)
    state\
        daemon\
            daemon.lock      # exclusive single-instance lock
            health.json      # atomic health snapshot
            STOP_REQUESTED   # graceful stop sentinel
        tasks\
            <task-id>\
                state.json
                META.json
                inbox\
                outbox\
    logs\
        daemon\
            daemon.stdout.log
            daemon.stderr.log
        dispatcher\
            <timestamp>.json
        tasks\
            <task-id>.attempt-NNN.stdout.log
            <task-id>.attempt-NNN.stderr.log
    workspace\
        <project-id>\
            # per-project working copy or git worktree
```

## Config / state / log / workspace separation

- **config/** is read-only for the service account. Only administrators and
  the deployment pipeline write here. Contains the bridge registry and daemon
  configuration.
- **state/** is read-write for the service account. Contains the daemon lock,
  health JSON, stop sentinel, and per-task state. No secrets are stored here.
- **logs/** is append-only for the service account. Contains daemon logs,
    dispatcher logs, and per-task stdout/stderr logs. Logs may contain
    masked output only; the bridge and daemon apply sensitive-value
    masking before writing to any log or health state. Raw logs never
    preserve unmasked secrets.
- **workspace/** is read-write for the service account. Contains per-project
  working copies or git worktrees. Each project gets its own subdirectory.

## ACL expectations

| Path                        | Owner   | Service Account | Admins  | Users   |
|-----------------------------|---------|-----------------|---------|---------|
| config\                     | Admin   | Read            | Full    | None    |
| state\                      | Admin   | Read, Write     | Full    | None    |
| logs\                       | Admin   | Read, Append    | Full    | None    |
| workspace\                  | Admin   | Read, Write     | Full    | None    |
| scripts\                    | Admin   | Read, Execute   | Full    | None    |

The service account should be a dedicated low-privilege account, not an
administrator. It needs:
- Read access to config\ and scripts\
- Read/Write access to state\ and workspace\
- Read/Append access to logs\
- No network access unless the bridge dispatches to remote SSH workers
- No ability to install services or modify system configuration

## Health JSON schema

The daemon writes `health.json` atomically to `state\daemon\health.json`:

```json
{
    "schemaVersion": 1,
    "daemonVersion": "1.3.0",
    "status": "running",
    "pid": 12345,
    "startTime": "2026-09-08T21:52:04Z",
    "iteration": 42,
    "lastSuccessTime": "2026-09-08T21:58:00Z",
    "lastError": "",
    "lastErrorAt": "",
    "maxWorkers": 3,
    "intervalSeconds": 30,
    "updatedAt": "2026-09-08T21:58:30Z"
}
```

Fields:
- `status`: running, stopping, or stopped
- `pid`: current daemon process ID
- `startTime`: daemon start time (ISO 8601)
- `iteration`: loop iteration count
- `lastSuccessTime`: last successful loop action time
- `lastError`: masked last error summary (no secrets)
- `lastErrorAt`: when the last error occurred
- `maxWorkers`: configured max concurrency (default 3)
- `intervalSeconds`: configured loop interval (default 30)
- `updatedAt`: when health was last written

## Backoff strategy

On child command failure, the daemon applies bounded exponential backoff:
- Base delay: 2 seconds (configurable)
- Delay = base * 2^(failureCount - 1)
- Maximum delay: 300 seconds (configurable)
- Minimum delay: 1 second

The daemon stays alive unless the configuration is invalid (e.g., bridge
script not found). It never spins rapidly.

## Graceful shutdown

- `bridge-daemon.ps1 stop` writes a STOP_REQUESTED sentinel file.
- The running daemon checks the sentinel at the top of each loop, after each
  action, and every 1 second during sleep.
- The daemon writes final health with status "stopped" and releases the lock.
- The stop command waits up to ShutdownTimeoutSeconds (default 60) for the
  lock to be released.

## Service installation (future)

The daemon scripts are ready for a future deployment step. This task does NOT
install or configure any service, scheduled task, or system component.

**Accurate boundary:** `sc.exe create` cannot directly host an ordinary
PowerShell script as a native Windows service. To run the supervisor in
production, use one of the following approaches after separate review:

1. **Task Scheduler** -- Create a scheduled task that runs
   `pwsh.exe -NoProfile -File ... bridge-daemon.ps1 run` at logon or on a
   trigger. This is the simplest option for a PowerShell supervisor.
2. **SCM-compatible service host/wrapper** -- Use a real service wrapper
   (e.g., NSSM, WinSW, or a custom C# service host) that manages the
   PowerShell process lifecycle and forwards signals to the daemon. This
   requires separate review of the wrapper security and reliability.
