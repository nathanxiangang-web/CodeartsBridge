# transport module

> Responsibility: Worker execution transport. Agent transport is the only one in normal use.

## Key files

- `src/bridge/transport/base.py` — Transport base class (TransportBase, TransportResult)
- `src/bridge/transport/agent.py` — Agent transport (HTTP API to Worker Agent on :8765)

## Agent transport

The Bridge talks to each Worker over HTTP:

```
Bridge -> POST /v1/jobs          (create job)
Bridge -> GET  /v1/jobs/<id>     (poll status)
Bridge -> GET  /v1/jobs/<id>/events?cursor=N  (incremental events)
Bridge -> POST /v1/jobs/<id>/cancel  (cancel)
```

The Worker Agent is a daemon (`bridge-worker-agent`) listening on :8765. No SSH, no local process spawn, no remote worktree in normal use.

## TransportBase.run signature

```python
def run(
    self, project, worker, task_dir, task_id,
    mode="auto", timeout_seconds=1800, soft_timeout_seconds=1500,
    session_id=None, attempt=0, baseline=None, quiet=False,
    model=None,
) -> TransportResult
```

## Model passing

All transports accept a `model` parameter and forward it to `new_worker_run_arguments(model=model or REQUIRED_MODEL)`.
