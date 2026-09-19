# runtime module

> Responsibility: Process lifecycle, timeout, cancellation, event echo

## Key files

- `src/bridge/runtime/process_supervisor.py` — Process management
- `src/bridge/runtime/timeout.py` — Soft/hard timeout
- `src/bridge/runtime/events.py` — Event echo
- `src/bridge/runtime/heartbeat.py` — Heartbeat
- `src/bridge/runtime/cancellation.py` — Cancellation
- `src/bridge/runtime/session.py` — Session
- `src/bridge/runtime/recovery.py` — Recovery

## Process lifecycle

```
RUNNING -> CANCEL_REQUESTED -> terminate -> grace period -> kill if needed -> CANCELLED
```

## Timeout

```
RUNNING
  ├── soft deadline -> request checkpoint -> ASSISTANCE_REQUIRED
  └── hard deadline -> force kill
```

## Event stream

```
Worker -> incremental event reader -> sanitized normalizer -> events.jsonl -> state snapshot -> UI
```

Events have a monotonically increasing `seq`. Supported types: status, heartbeat, tool, test, warning, terminal.

## STALE detection

```
RUNNING + heartbeat fresh -> LIVE
RUNNING + heartbeat timeout -> STALE
terminal state -> DONE / FAILED / BLOCKED
```

STALE is a UI-observable state only; it does not change the canonical task state.
