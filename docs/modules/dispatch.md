# dispatch module

> Responsibility: Task dispatch and Worker assignment

## Key files

- `src/bridge/dispatch.py` — Core dispatch logic
- `src/bridge/scheduler/` — Scheduler package
  - `matcher.py` — Role matching
  - `dependency.py` — Dependency resolution
  - `capacity.py` — Capacity planning
  - `affinity.py` — Host affinity
  - `lease.py` — Lease management
  - `planner.py` — Dispatch planning

## Core functions

- `execute_dispatch()` — Unified CLI dispatch entry
- `select_dispatch_plan()` — Select a dispatch plan
- `check_host_affinity()` — Worker-host match check

## Dispatch flow

```
plan -> claim task -> QUEUED -> spawn Worker via Agent transport -> return dispatch result
```

## Dispatch factors

- dependsOn (dependencies)
- priority
- worker capability
- worker availability
- host (host affinity)
- workspace conflict
- retry count
