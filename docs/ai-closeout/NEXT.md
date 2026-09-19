# NEXT — 下一位 AI 直接从这里开工

## 当前插队任务：Agent Runtime Truth

先读并执行：

```
docs/ai-closeout/06-AGENT-RUNTIME-TRUTH.md
```

现场已确认 Agent 主链已经工作，但还有两个真实断点：

```
1. CODEARTS_OUTBOX 在 projectRoot 外，导致 CodeArts 内置 write/edit 被拒绝
2. UI busy/idle 仍依赖 Bridge task state，Agent Job 还在跑时会错误显示“空闲”
```

请新建小分支：

```
fix/agent-runtime-truth
```

只修这两件事，不混入 dispatch / supervision / policy / UI 其它功能。

完成后再继续下面的收口顺序。

---


不要重新规划大架构，按顺序执行。

## 第一项：修生命周期真相

目标文件：

```
src/bridge/architect_loop.py
src/bridge/integration.py
src/bridge/state.py
src/bridge/core/state.py
相关 tests
```

必须实现：

```
Review PASS 只到 APPROVED
Integration 真正开始时到 INTEGRATING
成功后 INTEGRATED -> DONE
失败到 INTEGRATION_FAILED
DONE 必须要求 integratedSha
```

先完成真实测试 Scenario A + G。

## 第二项：统一 dispatch

当前：

```
CLI dispatch -> dispatch.py
daemon -> dispatch.py
pipeline -> auto_dispatch.py -> scheduler/*
```

目标：

```
CLI dispatch
TaskLoop
都走同一个 scheduler/dispatch API
```

迁移完成后删除：

```
legacy dispatch planner
bridge-daemon
重复测试
```

Scenario B 必须通过。

## 第三项：把 Bridge 收成一个长期进程

目标：

```
bridge serve
  API/UI
  + 唯一 TaskLoop
```

MCP 不默认启动。

禁止同时要求用户维护：

```
bridge serve
bridge-daemon
bridge pipeline
```

三个长期服务。

## 第四项：裁掉假 Supervision

先证明当前默认 Supervisor 是否真的注册过任务 deadline。

如果没有：

- 不继续修 flag。
- 不继续加 shadow mode。
- 删除 no-op 路径。
- Agent Watchdog 保持唯一 Worker 进程生命周期 owner。
- Bridge 只保留最小 stale/inflight reconciliation。

## 第五项：删除残留旧世界

优先：

```
policy/*
adaptive.py
cost.py
旧 UI tests/docs
旧 deployment token/10-page UI 文案
旧 runtime supervisor（确认无真实引用后）
```

最后重写 README。

---

每完成一项，在 PR 里明确回答：

```
这次删除了哪套平行实现？
现在唯一真实调用路径是什么？
真实场景怎么证明它工作？
```

回答不出来就不要合并。
