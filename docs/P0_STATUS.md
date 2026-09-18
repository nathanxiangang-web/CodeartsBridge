# P0 Completion Status — Docs Truth Reset

> 所有 P0 任务已完成并部署到 178.50 (bridge.service v2.0.0)
> 最后更新: 2026-09-18

## Wave 1 (commit 0cf338c) — DONE

| Task | Description | Status |
|------|-------------|--------|
| P0-01 | Unify dispatch: execute_dispatch() for CLI+daemon | DONE |
| P0-02 | Persist attempt number in state.py | DONE |
| P0-03 | Transport-aware workspace isolation | DONE |
| P0-08 S1 | E2E test skeleton + CI workflow | DONE |

## Wave 2 (commit 27bc573) — DONE

| Task | Description | Status |
|------|-------------|--------|
| P0-07 | Canonical result classifier (pure functions) | DONE |
| P0-04 | Host affinity check in dispatch | DONE |
| P0-05 | Process supervisor + CANCELLED state | DONE |

## Wave 3 (commit 10ae6e0) — DONE

| Task | Description | Status |
|------|-------------|--------|
| P0-06 | Soft timeout checkpoint + assistance delivery | DONE |

## Wave 4 (commit 05c1f93) — DONE

| Task | Description | Status |
|------|-------------|--------|
| P0-08 | Runtime event echo, heartbeat, stale detection | DONE |

## P0-09 (commit pending) — Docs Truth Reset

| Task | Description | Status |
|------|-------------|--------|
| P0-09 | E2E regression suite + CI | DONE (incremental, 74 E2E tests) |
| P0-09 | Docs Truth Reset | DONE (this document) |

## Test Summary

| Wave | E2E Tests | Unit Tests | Total |
|------|-----------|------------|-------|
| 1 | 11 | 49 | 60 |
| 2 | 34 | 49 | 83 |
| 3 | 46 | 49 | 95 |
| 4 | 74 | 49 | 123 |

## 178.50 Deployment Verification

- Bridge service: active (running)
- API health: healthy, v2.0.0
- E2E tests on 178.50: 74 passed in 0.10s
- Git HEAD: 05c1f93

## P0 Task → Commit Mapping

| P0 Task | Wave | Commit | Key Files |
|---------|------|--------|-----------|
| P0-01 | 1 | 0cf338c | dispatch.py (execute_dispatch) |
| P0-02 | 1 | 0cf338c | state.py (attempt param), worker.py |
| P0-03 | 1 | 0cf338c | dispatch.py (transport-aware workspace) |
| P0-04 | 2 | 27bc573 | dispatch.py (check_host_affinity) |
| P0-05 | 2 | 27bc573 | state.py (CANCELLED), runtime/process_supervisor.py |
| P0-06 | 3 | 10ae6e0 | runtime/timeout.py (handle_soft/hard_timeout) |
| P0-07 | 2 | 27bc573 | result_classifier.py |
| P0-08 | 4 | 05c1f93 | runtime/events.py (EventWriter/Reader/StaleDetection) |
| P0-09 | 1-4 | all | tests/e2e/ (74 tests), .github/workflows/ci.yml |