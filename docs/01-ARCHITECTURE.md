# CodeartsBridge Architecture

> Version: 2.0.0 | Updated: 2026-09-20

## Code structure

```
src/bridge/
├── cli.py                    # CLI entry (serve/dispatch/doctor/status)
├── dispatch.py               # Core dispatch (execute_dispatch, check_host_affinity)
├── state.py                  # State machine + auto timestamps
├── worker.py                 # Worker execution logic
├── config.py                 # Config parsing (ProjectConfig, WorkerConfig, Registry)
├── doctor.py                 # Health check
├── result_classifier.py      # Result classifier
├── telemetry.py              # Telemetry stats
├── atomic.py                 # Atomic file writes
├── codearts.py               # CodeArts CLI wrapper + model routing
├── git_ops.py                # Git operations
├── task.py                   # Task management
├── progress.py               # Progress display
├── scheduler/                # Scheduler package
│   ├── matcher.py            # Role matching
│   ├── dependency.py         # Dependency resolution
│   ├── capacity.py           # Capacity planning
│   ├── affinity.py           # Host affinity
│   ├── lease.py              # Lease management
│   └── planner.py            # Dispatch planning
├── runtime/
│   ├── timeout.py            # Soft/hard timeout
│   ├── events.py             # Event echo
│   ├── heartbeat.py          # Heartbeat
│   ├── process_supervisor.py # Process management
│   ├── cancellation.py       # Cancellation
│   ├── session.py            # Session
│   └── recovery.py           # Recovery
├── transport/
│   ├── base.py               # Transport base class
│   └── agent.py              # Agent transport (HTTP API, the one in use)
├── agent/                    # Worker Agent (daemon)
│   ├── cli.py                # Agent CLI entry
│   ├── server.py             # HTTP Server (:8765)
│   ├── runner.py             # CodeArts runner
│   ├── watchdog.py           # Process watchdog
│   ├── recovery.py           # Inflight recovery
│   └── store.py              # Job store
├── core/
│   ├── events.py             # EventStore (flock + rotation)
│   └── state.py              # State machine
├── api/server.py             # HTTP API server
├── application/              # Application service layer
└── web/                      # Read-only Web UI
    ├── index.html
    ├── styles/app.css
    └── js/pages/             # overview, tasks, task-detail, thinking
```

## State machine

```
READY -> QUEUED -> STARTING -> RUNNING -> REVIEW_REQUIRED -> DONE
                                    ↓
                              BLOCKED / ASSISTANCE_REQUIRED / AUTH_REQUIRED
                              RETRYABLE / FAILED / CANCELLED

REVIEW_REQUIRED -> FIX_REQUIRED -> QUEUED (retry)
```

State transitions auto-record timestamps: queuedAt, startedAt, runningAt, finishedAt, doneAt, reviewedAt, cancelledAt, etc.

## Model routing

Priority: worker.model > project.model > ROLE_MODEL_MAP[role] > REQUIRED_MODEL

Role mapping:
- architect -> reasoning model
- implement -> coding model
- review -> reasoning model
- test -> fast model

## Event stream

```
CodeArts/Worker -> incremental event reader -> sanitized normalizer
-> events.jsonl -> state heartbeat snapshot -> UI
```

- Events have a monotonically increasing seq
- STALE detection: RUNNING + heartbeat timeout -> STALE (does not change canonical state)
- Sensitive values are masked
- Model private reasoning is not exposed
