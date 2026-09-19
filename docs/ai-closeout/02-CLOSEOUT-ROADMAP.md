# 02 — 收口路线图

原则：**先让一条链真的完整，再删掉其他平行世界。**

---

## P0 — 先修“假闭环”

### P0-1 Review / Integration 状态语义

修改目标：

```
Worker 成功
-> REVIEW_REQUIRED

Review PASS
-> APPROVED

Integration 开始
-> INTEGRATING

cherry-pick + verify 成功
-> INTEGRATED
-> DONE

失败
-> INTEGRATION_FAILED
```

禁止 Review 代码直接写 `INTEGRATED` / `DONE`。

验收：

- Review PASS 后 git HEAD 不变，状态只能到 APPROVED。
- Integration 真正成功后才允许出现 integratedSha。
- DONE 时必须存在 integratedSha。
- Integration 失败不能留下 DONE。

### P0-2 只保留一个 Bridge 长期控制循环

推荐目标：

```
bridge serve
  -> API/UI
  -> 一个长期 TaskLoop
     -> review
     -> dispatch
     -> integrate
```

`bridge pipeline --once` 可以保留为诊断入口。

`bridge-daemon` 旧 dispatch 服务在迁移完成后删除。

不要长期维持：

```
serve + daemon + pipeline
```

三套长期运行方式。

### P0-3 调度只留一套

优先保留：

```
auto_dispatch.py
-> scheduler/planner.py
```

因为这条已经包含 lease / dependency / capacity 等当前任务模型。

迁移 CLI `dispatch` 到同一套 scheduler 后：

```
删除 dispatch.py 的平行 planner/executor
删除 daemon 对旧 dispatch 的依赖
```

如果某个 scheduler 子模块最终没有真实用途，再继续向下砍。

---

## P1 — Supervision 做真实性裁决

不要继续给现有监督架构补 flag。

先做一个问题：

> 当前真实 4 Worker 场景，Agent Watchdog + Bridge TaskLoop 还缺什么？

### 必须保留的能力

```
硬超时
进程回收
Agent 重启恢复
Bridge 重启后重新观察 inflight job
任务卡住能识别
```

### 默认删除候选

若没有真实验收场景证明必要：

```
supervision/flags.py
supervision/background.py
supervision/capacity.py
supervision/review_lock.py
ArchitectQueue
ArchitectReactor 的未接线 handler
shadow mode
polling/event 双 Review 开关
```

### Supervisor

当前 `pipeline.py` 默认 Supervisor 是 no-op Inspector + 空 Scheduler。

两个选项只能留一个：

A. 真正接线成长期单实例、真实任务 deadline 监督器。  
B. 删除整套 Bridge Supervision，只保留 Agent Watchdog + 简单 stale check。

按当前“做减法”方向，默认优先 B，除非真实故障案例证明 A 必要。

---

## P2 — 删除平行运行时

按引用审计逐项处理：

### Runtime Supervisor

候选：

```
src/bridge/runtime/supervisor.py
src/bridge/runtime/process_supervisor.py
runtime/session.py
runtime/heartbeat.py
runtime/timeout.py
runtime/recovery.py
```

先确认 Agent 主链路、取消、超时、恢复全部有替代，再删除。

### Policy

Worker 主链路已不使用，直接进入删除阶段：

```
src/bridge/policy/*
旧 Policy tests
旧 Policy docs
```

### Application Service

当前 application 层只迁了一半。

不要继续“双轨”。

选择：

```
CLI/API/Loop 全部统一到 application service
```

或者：

```
删除薄 application wrapper，直接调用唯一 domain/runtime API
```

哪种代码更少选哪种。

不要保留“create 用 v2，dispatch 用 v1，pipeline 用第三套”。

---

## P3 — 砍非核心 CLI / 服务

在真实主链稳定后，逐个判断：

```
adaptive-dispatch
cost
telemetry CLI
MCP 默认启动
projects/workers 单独 CLI
ssh-shell
remote-worktree
```

原则：

- UI 监控需要的数据 API 可以保留。
- 没有当前真实使用者的用户入口删除。
- MCP 如果保留，单独启动，不默认绑在 `bridge serve`。
- Agent 是主 transport；local 仅测试/救援；SSH 最多保留一个 fallback。
- 不维持 5 种 transport。

---

## P4 — 文档、部署和测试收口

必须一起改：

```
README.md
install.sh
deploy/*.service
deploy/*.sh
docs/modules/*
旧 roadmap
旧 UI 文档
旧 Policy 文档
```

最终 README 只能描述**当前真实运行方式**。

测试也要删旧世界：

- 不测试已经删除的 UI 页面。
- 不测试已经删除的 Policy 接线。
- 不测试旧 project×worker 配置。
- 不因为旧测试失败而恢复旧功能。

---

## 推荐 PR 顺序

```
PR-1  fix lifecycle truth
PR-2  one scheduler / one control loop
PR-3  remove fake supervision
PR-4  remove runtime/policy/legacy orchestration
PR-5  deployment + README truth
PR-6  real 4-worker acceptance
```

每个 PR 都要求“删掉的复杂度 > 新增复杂度”。
