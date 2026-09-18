# worker 模块

> 职责：Worker 执行逻辑，含策略门控和模型路由

## 关键文件

- `src/bridge/worker.py` — Worker 执行入口
- `src/bridge/codearts.py` — CodeAr6ts CLI 封装 + 模型路由（P1-03）
- `src/bridge/result_classifier.py` — 结果分类器（P0-07）

## 执行流程

```
run_worker()
  → set STARTING
  → load policy profile
  → preChecks (if profile exists)
  → set RUNNING
  → resolve_model(role, worker, project)
  → transport.run(model=resolved_model)
  → parse telemetry
  → result classifier
  → postChecks (if profile exists)
  → set terminal state
```

## 模型路由（P1-03）

优先级：worker.model > project.model > ROLE_MODEL_MAP[role] > REQUIRED_MODEL

`resolve_model()` 在 `codearts.py` 中实现。`"default"` 和空字符串作为 sentinel 触发角色映射。

## 策略门控（P1-04）

- preCheck 失败（onFailure=block）→ BLOCKED，不执行 transport.run
- postCheck 失败（onFailure=block）→ BLOCKED
- approvalGate → REVIEW_REQUIRED（等待批准）
- 无 profile → 跳过（向后兼容）

## 结果分类（P0-07）

```
RESULT + TESTS + DIFF → REVIEW_REQUIRED
BLOCKER.md → BLOCKED
CHECKPOINT + ASSISTANCE_REQUEST → ASSISTANCE_REQUIRED
authorization error → AUTH_REQUIRED
temporary retry condition → RETRYABLE
cancel → CANCELLED
exit 0 but incomplete → FAILED
transport/protocol failure → FAILED
```