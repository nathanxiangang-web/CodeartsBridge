# policy 模块

> 职责：策略门控（preChecks/postChecks/approvalGate）

## 关键文件

- `src/bridge/policy/engine.py` — 策略引擎（profile 加载/验证）
- `src/bridge/policy/runtime.py` — 策略运行时（check 执行）
- `src/bridge/policy/integration.py` — 策略接入执行链（P1-04）
- `src/bridge/policy/timeout.py` — 超时策略
- `policies/default.json` — 默认 profile

## 门控流程

```
preChecks → Worker → postChecks → approvalGate → REVIEW_REQUIRED
```

## 核心函数

- `load_profile_for_project(config_dir, project_id)` — 加载 profile
- `evaluate_pre_checks(profile, task_dir, project_root, role)` — 前置检查
- `evaluate_task_policy(profile, task_dir, project_root, role)` — 后置检查
- `should_block_task(result)` — 是否阻塞
- `should_transition_to_review(result)` — 是否进入 REVIEW

## Phase ID 约定

- `pre-check` — 前置检查 phase
- `post-check` — 后置检查 phase
- 其他 phase ID 也作为 postCheck 评估

Phase ID 必须匹配 `^[a-z0-9][a-z0-9._-]*$`（小写字母、数字、点、下划线、连字符）。

## Check 执行

1. 如果 skip → passed=True
2. 如果无 command → passed=True（不检查 evidence）
3. 运行 command，检查 exit code
4. 检查 required_evidence（相对于 task_dir/outbox/）

## onFailure 模式

- `block` — 阻塞任务（→ BLOCKED）
- `warn` — 警告但继续
- `continue` — 无动作