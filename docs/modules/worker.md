# worker module

> Responsibility: Worker execution logic and model routing

## Key files

- `src/bridge/worker.py` — Worker execution entry
- `src/bridge/codearts.py` — CodeArts CLI wrapper + model routing
- `src/bridge/result_classifier.py` — Result classifier

## Execution flow

```
run_worker()
  -> set STARTING
  -> set RUNNING
  -> resolve_model(role, worker, project)
  -> transport.run(model=resolved_model)
  -> parse telemetry
  -> result classifier
  -> set terminal state
```

## Model routing

Priority: worker.model > project.model > ROLE_MODEL_MAP[role] > REQUIRED_MODEL

`resolve_model()` lives in `codearts.py`. `"default"` and empty string act as sentinels that trigger role mapping.

## Result classification

```
RESULT + TESTS + DIFF -> REVIEW_REQUIRED
BLOCKER.md -> BLOCKED
CHECKPOINT + ASSISTANCE_REQUEST -> ASSISTANCE_REQUIRED
authorization error -> AUTH_REQUIRED
temporary retry condition -> RETRYABLE
cancel -> CANCELLED
exit 0 but incomplete -> FAILED
transport/protocol failure -> FAILED
```
