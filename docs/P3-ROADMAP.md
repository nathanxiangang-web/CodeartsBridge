# P3 Roadmap: Data-Driven Development Efficiency

> Updated: 2026-09-19 | Phase: P3 | Baseline: 6753939
>
> Goal: make CodeartsBridge improve development throughput using measured evidence,
> without turning the bridge into an opaque self-tuning workflow engine.

## Principle

P3 follows one rule:

**Measure -> explain -> recommend -> guard -> automate.**

The scheduler must not learn from metrics whose definitions are unstable. Therefore
P3 begins with telemetry truth before worker scoring, model routing, or adaptive
priority changes.

## P3-01: Telemetry Truth

**Status:** IN PROGRESS

Make existing metrics decision-grade.

Scope:
- define explicit denominators for first-pass, fix, retry, and timeout rates
- calculate throughput from wall-clock completion span instead of summed task durations
- expose per-worker utilization over a shared execution window
- support scalar and structured token payloads
- add machine-readable `bridge telemetry --json`
- regression tests for exact metric semantics

Exit gate:
- all Python 3.11/3.12/3.13 CI suites green
- metric definitions documented in code and tests
- no scheduler behavior change in this task

## P3-02: Worker Performance Profiles

**Status:** PLANNED

Build historical worker statistics by role and workload class:
- sample count
- first-pass rate
- median execution time
- retry/timeout rate
- recent utilization

The scheduler may consume a worker score only after a minimum sample threshold.
With insufficient evidence, it falls back to current static matching.

## P3-03: Model Cost / Quality Routing

**Status:** PLANNED

Track model-level latency, token cost, and review outcome by role.

Routing policy:
- architect/review: protect quality first
- implementation: optimize quality-adjusted latency
- test/repetitive work: prefer lower-cost models when quality guardrails hold

No model is automatically demoted on a tiny sample.

## P3-04: Adaptive Queue and Critical Path

**Status:** PLANNED

Use measured duration and queue delay to improve dispatch order:
- predicted duration by role/task class
- critical-path boost
- starvation protection
- worker capacity balancing
- bottleneck detection

Every adaptive decision must remain explainable in the dispatch result.

## P3-05: Optimization Guardrails

**Status:** PLANNED

Add a recommendation layer before autonomous tuning:
- emit proposed scheduling/routing changes
- show evidence and sample size
- compare before/after windows
- allow rollback to static defaults
- persist an audit trail for accepted automatic changes

## Success Metrics

P3 is successful when the bridge can answer, from persisted data:

1. Which worker is fastest for this role without lowering first-pass quality?
2. Where is queue time being lost?
3. Which model/role pairing gives the best quality-adjusted cost?
4. What is the current worker utilization and bottleneck?
5. Did the last optimization actually improve throughput?

## Non-Goals

- reinforcement-learning scheduler
- opaque automatic policy mutation
- large workflow DSL
- replacing human escalation for BLOCKER/AUTH_REQUIRED
- optimizing a metric without minimum sample and quality guardrails
