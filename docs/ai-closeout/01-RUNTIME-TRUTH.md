# 01 — 当前运行真相审计

审计基线：`main@14652b4f6a70e5f89ec78fde19aaa3c0a9e3ef74`

这份文档只记录“代码现在实际怎么走”，不记录设计愿望。

## A. 已经真实工作的部分

### Worker Agent 链路

当前 Agent Server 会真正启动 Runner，并且每 2 秒运行 Watchdog：

```
AgentServer.start()
  -> Runner
  -> Watchdog loop
  -> completion / timeout / recovery
```

相关代码：

- `src/bridge/agent/server.py`
- `src/bridge/agent/runner.py`
- `src/bridge/agent/watchdog.py`
- `src/bridge/agent/store.py`
- `src/bridge/transport/agent.py`

这条链路刚完成 UI 回显修复，是目前应该保留的 Worker 主链路。

### UI

当前真实 UI 已经收成：

```
overview
tasks
task-detail
thinking
```

其中导航只暴露：

```
overview / tasks / thinking
```

UI 定位已经正确：只读监控，不做第二控制平面。

---

## B. 当前最严重的问题：Bridge 有多套控制循环

现在至少同时存在三种控制方式：

### 1. bridge serve

`src/bridge/cli.py::cmd_serve`

实际只启动：

```
HTTP API
Web UI
MCP（默认开启）
```

**不会自动运行 pipeline。**

也就是说，只启动 `bridge serve` 时，自动 dispatch / review / integrate 不会因为 Web 服务启动而自动发生。

### 2. bridge-daemon

`src/bridge/daemon.py`

systemd 当前配置：

```
ExecStart=/usr/bin/python3 -m bridge.daemon run
```

它走的是：

```
bridge.daemon
  -> dispatch.py
  -> execute_dispatch()
  -> worker
```

它只负责旧式 dispatch 循环，不负责当前 pipeline 的 review / integrate。

而且 `deploy/bridge-daemon.service` 的 WorkingDirectory 还是：

```
/home/nathan/bridge
```

与当前项目实际 `/home/nathan/bridge-python` 体系不一致，属于明显旧部署残留。

### 3. bridge pipeline

`src/bridge/pipeline.py`

它走的是：

```
polling architect review
-> auto_dispatch
-> integrate_loop
-> conflict check
```

dispatch 又走：

```
auto_dispatch.py
-> scheduler/planner.py
-> lease/capacity/matcher/affinity
```

所以目前存在：

```
旧 dispatch.py 路径
+
新 auto_dispatch/scheduler 路径
```

两套调度逻辑同时活着。

---

## C. CLI 本身也是“新旧混搭”

`src/bridge/cli.py` 当前：

### 已切到 application service

```
create
cancel
review-pass
review-fix
projects
workers
```

### 仍走旧模块

```
dispatch -> dispatch.py
run      -> worker.py
integrate -> integration.py
```

### pipeline 又走另一套

```
pipeline -> auto_dispatch.py -> scheduler/*
```

这说明 Application Service 并没有真正成为统一应用层，只是部分命令迁了一半。

---

## D. Review 状态目前存在“假闭环”

这是下一步 P0。

`src/bridge/architect_loop.py::review_task` 在 PASS 后当前直接执行：

```
REVIEW_REQUIRED
-> APPROVED
-> INTEGRATING
-> INTEGRATED
-> DONE
```

但这里**没有真正执行 git integration**。

真正 cherry-pick 在：

```
src/bridge/integration.py::integrate_task()
```

而 `integrate_loop()` 又只扫描：

```
DONE && no integratedSha
```

因此现在实际语义是：

```
审查 PASS
-> 状态先假装已经 INTEGRATED/DONE
-> pipeline 后面再真的 cherry-pick
```

这正是“流程走完了，但功能其实还没发生”的典型问题。

正确语义必须改成：

```
REVIEW_REQUIRED
-> APPROVED
-> INTEGRATING
-> 真正 cherry-pick + verify
-> INTEGRATED
-> DONE
```

失败则：

```
INTEGRATION_FAILED
```

DONE 必须代表真实完成，不能代表“准备去集成”。

---

## E. Supervision 当前大量是“调用了流程，但没有产生实际效果”

`supervision.json` 当前：

```
supervisionEnabled = true
architectPollingReview = true
architectEventReview = false
architectBackgroundEnabled = false
capacityEventsEnabled = false
```

### 1. Supervisor 默认 Inspector 是 no-op

`pipeline.py::_DefaultInspector.inspect()` 只返回空 `InspectionResult`。

### 2. pipeline 每个 cycle 会重新创建 Supervisor

```
_build_default_supervisor()
-> new DeadlineScheduler()
-> new Supervisor()
```

正常 pipeline 路径中没有看到：

```
on_task_started()
recover()
```

给这个新 Scheduler 注入实际 task deadline。

所以 `supervision_tick_called=True` 并不等于真的监督了任务。

### 3. Event Reactor 默认也是空队列

`_build_default_reactor()` 每次创建：

```
ArchitectReactor(ArchitectQueue(), ...)
```

但当前默认：

```
architectEventReview = false
```

即使打开，如果没有真实生产者向这一个队列持续写事件，新建空队列仍可能什么都不处理。

### 4. Background / Capacity

默认关闭，而且不是当前核心问题。

结论：不要继续修补 feature flags。先决定是否真的需要这套 Supervision。若无法用真实 E2E 证明价值，直接删除。

---

## F. Worker 之外还有第二套 Runtime Supervisor

存在：

```
src/bridge/runtime/supervisor.py
src/bridge/runtime/process_supervisor.py
```

但当前 Agent 主链路已经有：

```
Agent Runner
Agent Watchdog
Agent Recovery
```

而 `worker.py` 是直接调用 transport，并没有把 Agent 执行交给 `runtime.Supervisor`。

这组 runtime supervisor 应当进入“引用审计 -> 删除候选”，不要因为测试多就默认它必须留下。

---

## G. Policy 已退出真实 Worker 主链路，但代码还在

`worker.py` 当前已经不再执行 Policy Engine pre/post gate。

但目录仍存在：

```
src/bridge/policy/
tests/e2e/test_policy_integration.py
tests/Test-Policy*.ps1
docs/modules/policy.md
```

这会持续误导 AI 以为 Policy 还是当前架构核心。

收口时应删除或完整归档，不应维持“代码还在但不工作”的状态。

---

## H. 文档严重落后于代码

根目录 `README.md` 当前仍描述：

- 10 个 UI 页面
- Token 认证
- 多 transport
- Policy
- 旧 CSS/component 结构
- 旧 Worker 配置字段
- `/api/events/stream`
- Agent token 安装流程

但当前 main 已经做过 Local-First 大幅减法。

这不是普通文档问题，而是**AI 开发质量问题**：后续模型会把旧 README 当真，再次把已经砍掉的功能加回来。

因此 README / install / deploy 文档同步必须属于收口任务，不是最后再补。

---

## I. 当前判断

项目目前不是“功能不够”，而是：

```
功能数量 > 真正主链路数量
```

主要风险不是少功能，而是：

```
同一件事有两三套实现
测试能跑
默认运行却没接线
状态提前宣布成功
文档继续描述已经删除的世界
```

下一阶段必须以删除分叉、建立唯一运行真相为主。
