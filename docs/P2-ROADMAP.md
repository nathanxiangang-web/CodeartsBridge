# P2 Roadmap: AI Automated Development Pipeline

> Version: 1.0.0 | Updated: 2026-09-18 | Phase: P2 | Baseline: 2f1ee7a

## Definition

P2 turns CodeartsBridge from a manually-dispatched task control plane into a
continuously running AI development pipeline. The Architect AI plans and
reviews, the Bridge auto-dispatches and integrates, and Workers produce
verifiable code without human intervention for each step.

**Core shift:** User triggers a requirement, the pipeline runs autonomously
until all tasks are integrated or a BLOCKER escalates.

## Prerequisites

- P0 (trusted control plane): DONE
- P1 (efficiency optimization): DONE
- Baseline commit: `2f1ee7a` (v2.1.0)
- Available infrastructure: 4 Workers (W01-W03 dev, W04 QA), bridge.service on 178.50

## Pipeline Overview

```
Requirement
  |
  v
Architect AI Loop (P2-02)        plan tasks, review output
  |
  v
Auto-Dispatch Engine (P2-01)     resolve deps, select worker, dispatch
  |
  v
Worker executes                  SEARCH -> EDIT -> TEST -> DELIVER
  |
  v
Architect Review                 PASS | FIX -> re-dispatch
  |
  v
Integration Automation (P2-03)   merge isolated patch into main
  |
  v
Conflict Resolution (P2-04)      detect overlap, rebase or re-dispatch
  |
  v
Pipeline Orchestrator (P2-05)    loop until DONE or BLOCKER
```

## Task Breakdown

### P2-01: Auto-Dispatch Engine

**Objective:** Automatically dispatch READY tasks to available Workers based on
dependency resolution, priority, capacity, and host affinity. Eliminate manual
`bridge dispatch` calls for routine task flow.

**Dependencies:** P1-02 (priority scheduling), P0-04 (host affinity)

**Scope:**
- New module `src/bridge/auto_dispatch.py`
- CLI command `bridge auto-dispatch [--loop] [--interval N]`
- Integration with existing `scheduler/` package (priority, dependency, capacity, affinity)
- Idempotency guard: no double-dispatch for the same task

**Acceptance Criteria:**
1. `bridge auto-dispatch` picks all READY tasks whose dependencies are DONE,
   selects the best available Worker, and dispatches without manual intervention
2. Respects priority ordering, Worker capacity limits, and host affinity rules
3. Idempotent: running two auto-dispatch loops concurrently does not
   double-dispatch any task
4. `--loop` mode runs continuously at the configured interval until stopped
5. E2E test: create 3 tasks with a dependency chain (A -> B -> C),
   auto-dispatch resolves and dispatches in correct order
6. No regression in existing `bridge dispatch` manual path

**Out of Scope:** Architect AI planning (P2-02), integration (P2-03)

---

### P2-02: Architect AI Loop

**Objective:** Implement the Architect AI decision loop that automatically plans
tasks from requirements, reviews completed Worker output, and creates follow-up
tasks. The Architect reads project state, decides WHAT, and emits task
definitions; it does not write implementation code.

**Dependencies:** P2-01 (auto-dispatch)

**Scope:**
- New module `src/bridge/architect_loop.py`
- CLI command `bridge architect-loop [--loop]`
- Planning: requirement text -> task META.json + inbox/TASK.md
- Review: inspect REVIEW_REQUIRED tasks -> PASS | FIX
- FIX creates a new narrow task linked to the original
- Integration with `codearts.py` for AI model invocation (reasoning model)

**Acceptance Criteria:**
1. `bridge architect-loop` inspects all REVIEW_REQUIRED tasks, runs review,
   and transitions state to DONE (PASS) or creates a FIX task
2. Planning mode: given a requirement description, the Architect creates
   well-formed META.json + inbox/TASK.md with objective, dependencies, and
   acceptance criteria
3. Review produces PASS or FIX with narrow, scoped feedback (not a redesign)
4. FIX tasks are linked to the original task via `dependsOn` and inherit
   context
5. The Architect never writes implementation code; it only creates task
   definitions and review verdicts
6. E2E test: simulate a task in REVIEW_REQUIRED with valid output,
   architect-loop transitions it to DONE; simulate invalid output,
   architect-loop creates a FIX task

**Out of Scope:** Auto-dispatch mechanics (P2-01), integration merge (P2-03)

---

### P2-03: Integration Automation

**Objective:** Automatically integrate reviewed-and-passed Worker patches into
the main branch. Detect merge readiness, perform isolated merge, run post-merge
tests, and update the baseline.

**Dependencies:** P2-01 (auto-dispatch), P2-02 (architect loop for PASS gate)

**Scope:**
- New module `src/bridge/integration.py`
- CLI command `bridge integrate [--task-id ID] [--loop]`
- Pre-merge gate: verify task state is DONE (review PASS)
- Isolated merge: cherry-pick or merge the task commit into main
- Post-merge: run focused tests, update baseline SHA on pass
- Rollback: revert merge and mark task INTEGRATION_FAILED on test failure

**Acceptance Criteria:**
1. `bridge integrate --task-id ID` merges the task isolated commit into main
   only if the task state is DONE
2. Post-merge focused tests pass; baseline SHA updated in registry
3. On post-merge test failure: merge is reverted, task marked
   INTEGRATION_FAILED, Architect notified
4. `--loop` mode continuously integrates all DONE tasks
5. Integration is serialized: no two tasks integrate simultaneously into main
6. E2E test: create a task with a valid patch and DONE state, integrate,
   verify main branch contains the change and baseline SHA updated

**Out of Scope:** Conflict resolution logic (P2-04), Architect review (P2-02)

---

### P2-04: Conflict Resolution

**Objective:** Detect and resolve conflicts when multiple Workers produce
overlapping changes to shared files. Provide automated detection, targeted
rebase, and re-dispatch of conflicting tasks with conflict context.

**Dependencies:** P2-03 (integration automation)

**Scope:**
- New module `src/bridge/conflict.py`
- File-level conflict detection between pending integration patches
- Auto-rebase for non-overlapping file changes
- Conflict handling: mark task CONFLICT, capture diff context, notify Architect
- Re-dispatch: Architect creates a FIX task with conflict context for the Worker

**Acceptance Criteria:**
1. During integration, file-level conflicts between pending patches are
   detected before merge attempt
2. Non-conflicting patches (disjoint file sets) auto-rebase cleanly
3. Conflicting patches: task marked CONFLICT, conflict diff captured in
   outbox, Architect notified via ASSISTANCE_REQUEST
4. Architect can create a FIX task with conflict context; Worker receives
   the conflicting diff as part of the task inbox
5. No silent data loss: every conflict produces an audit trail in events.jsonl
6. E2E test: two tasks modifying the same file, second integration detects
   conflict and marks task CONFLICT

**Out of Scope:** Merge strategy selection (P2-03), Architect decision logic (P2-02)

---

### P2-05: Pipeline Orchestrator

**Objective:** Tie auto-dispatch, Architect loop, integration, and conflict
resolution into a single continuous pipeline. `bridge pipeline` runs the full
loop autonomously: plan -> dispatch -> review -> integrate -> resolve -> repeat.

**Dependencies:** P2-01, P2-02, P2-03, P2-04

**Scope:**
- New module `src/bridge/pipeline.py`
- CLI command `bridge pipeline [--config FILE]`
- Pipeline state machine: persisted and recoverable on restart
- Cycle: architect-plan -> auto-dispatch -> worker-execute -> architect-review
  -> integrate -> conflict-resolve -> repeat
- Stop conditions: BLOCKER, AUTH_REQUIRED, idle queue
- Telemetry: pipeline cycle time, first-pass rate, conflict rate, throughput

**Acceptance Criteria:**
1. `bridge pipeline` runs the end-to-end loop continuously
2. Pipeline state is persisted to disk; on bridge restart, pipeline resumes
   from the last completed step without re-dispatching in-flight tasks
3. Pipeline stops on BLOCKER or AUTH_REQUIRED; continues on ordinary Worker
   failures (task FAILED -> Architect creates FIX)
4. Pipeline idles (no busy-wait) when no tasks are READY or REVIEW_REQUIRED
5. Telemetry records: cycle time per loop, first-pass rate, conflict rate,
   Worker utilization, throughput (tasks/hour)
6. E2E test: full pipeline with 3 tasks from requirement to integrated main,
   verify all tasks DONE, main branch updated, no orphan state
7. E2E test: pipeline restart mid-flight does not double-dispatch or lose state

**Out of Scope:** New Worker types, UI changes, deployment automation

---

## Dependency Graph

```
P2-01 (Auto-Dispatch)
  |
  +---> P2-02 (Architect AI Loop)
  |       |
  |       v
  +---> P2-03 (Integration Automation)
  |       |
  |       v
  |       P2-04 (Conflict Resolution)
  |               |
  |               v
  +-----------> P2-05 (Pipeline Orchestrator)
```

## Execution Order

| Wave | Tasks | Parallelizable | Entry Condition |
|------|-------|----------------|-----------------|
| 1 | P2-01 | Yes (single task) | P1 complete |
| 2 | P2-02, P2-03 | Yes (disjoint modules) | P2-01 complete |
| 3 | P2-04 | Yes (single task) | P2-03 complete |
| 4 | P2-05 | Yes (single task) | P2-01 through P2-04 complete |

## Constraints

- Each task follows Worker rules: one deliverable, one failure domain, independently testable
- No task modifies more than one core boundary
- Each task target: 10 min, soft: 12 min, hard: 15 min
- FIX tasks only repair the current deliverable narrow defect
- All new modules go under `src/bridge/` following existing package structure
- E2E tests go in `tests/e2e/` following existing test conventions
- No database, no complex workflow DSL, no permission system (bridge stays simple)

## Success Metrics

```
Pipeline cycle time:   < 30 min per task (plan to integration)
First-pass rate:       > 70% of tasks PASS on first review
Conflict rate:         < 10% of integrations
Worker utilization:    > 80% during active pipeline
Human interventions:   only on BLOCKER escalations
```

## Out of Scope for P2

- P3 (data-driven optimization): metrics-driven scheduling, cost optimization
- UI dashboard for pipeline visualization
- Multi-project pipeline (one pipeline per project)
- Production deployment automation
- New Worker types or roles
