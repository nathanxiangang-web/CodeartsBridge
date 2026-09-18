# dispatch 模块

> 职责：任务调度与 Worker 分配

## 关键文件

- `src/bridge/dispatch.py` — 核心调度逻辑
- `src/bridge/scheduler/` — 调度器包
  - `priority.py` — 优先级调度（P1-02）
  - `matcher.py` — 角色匹配
  - `dependency.py` — 依赖解析
  - `capacity.py` — 容量规划
  - `affinity.py` — 亲和性（P0-04）
  - `lease.py` — 租约管理
  - `planner.py` — 调度编排

## 核心函数

- `execute_dispatch()` — 统一 CLI/daemon 调度入口（P0-01）
- `select_dispatch_plan()` — 选择调度计划
- `check_host_affinity()` — Worker-host 匹配检查（P0-04）

## 调度流程

```
plan → claim task → QUEUED → spawn Worker → return dispatch result
```

CLI 与 daemon 调用同一实现。

## 调度考虑因素

- dependsOn（依赖）
- critical path（关键路径）
- priority（优先级）
- estimated duration（预估时长）
- worker capability（Worker 能力）
- worker availability（Worker 可用性）
- host（主机亲和性）
- workspace conflict（工作区冲突）
- quota（配额）
- retry count（重试次数）