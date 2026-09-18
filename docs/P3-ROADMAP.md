# P3 Roadmap: Data-Driven Development Efficiency

> Updated: 2026-09-19 | Baseline: 874c9b2
>
> Current reality: P3-01 adaptive scheduling and P3-02 cost tracking already exist
> on main. P3-03 hardens the telemetry they depend on before further automation.

## Operating Principle

**Measure -> explain -> recommend -> guard -> automate.**

Adaptive behavior is only as good as its historical data. Every automated routing
or timeout decision must use explicit metric definitions, enough samples, and a
fallback to static policy.

## P3-01: Adaptive Scheduling

**Status:** DONE (existing main)

Implemented in `src/bridge/adaptive.py`:
- historical worker performance
- adaptive timeout recommendation
- preferred-worker recommendation
- `bridge adaptive-dispatch`

Follow-up guardrails are tracked below because the first version depends on
telemetry semantics that were originally too loose.

## P3-02: Cost Tracking

**Status:** DONE (existing main)

Implemented in `src/bridge/cost.py`:
- token/cost estimation
- project / worker / role aggregation
- optimization recommendations
- `bridge cost`

## P3-03: Telemetry Truth & Machine-Readable Metrics

**Status:** IN PROGRESS

Scope:
- explicit denominators for first-pass, fix, retry, and timeout rates
- wall-clock throughput instead of summed task durations
- per-worker utilization over a shared observation window
- runtime-assigned worker identity takes precedence over requested/static META worker
- scalar and structured token payload support
- `bridge telemetry --json`
- exact semantic regression tests

Exit gate:
- Python 3.11/3.12/3.13 CI green
- no scheduling behavior change in this task
- adaptive.py continues to consume the same TaskMetrics API, now with more accurate data

## P3-04: Adaptive Scheduling Guardrails v2

**Status:** PLANNED

Harden the current adaptive scheduler:
- worker performance segmented by role (and project when sample size allows)
- minimum sample + confidence/fallback rules
- explain why a worker/timeout was selected
- separate recommendation from mutation for auditability
- define dry-run semantics explicitly
- prevent a globally fast worker from being preferred for an unrelated role

## P3-05: Quality-Adjusted Model Routing

**Status:** PLANNED

Combine model routing with telemetry and cost:
- first-pass quality by role/model
- median latency
- token/cost profile
- minimum-sample guardrails
- quality floors for architect/review roles
- cost optimization only when quality remains above the floor

## P3-06: Queue / Critical-Path Optimization

**Status:** PLANNED

Use measured duration and queue delay to improve dispatch order:
- predicted duration by role/task class
- critical-path boost
- starvation protection
- worker capacity balancing
- bottleneck detection

Every adaptive decision must remain explainable in the dispatch result.

## P3-07: Optimization Audit & Rollback

**Status:** PLANNED

Before autonomous policy tuning:
- persist proposed and applied changes
- record evidence/sample size
- compare before/after windows
- provide static-policy fallback
- support rollback of automatic tuning

## Success Questions

P3 should eventually answer from persisted evidence:

1. Which worker performs best for this role without lowering first-pass quality?
2. Where is queue time being lost?
3. Which model/role pairing has the best quality-adjusted cost?
4. Which workers are under- or over-utilized?
5. Did an adaptive change actually improve throughput?
6. Why did the bridge make this routing/timeout decision?
