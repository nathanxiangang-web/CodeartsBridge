# CodeartsBridge v1.0 做减法重构开发文档

> 基线仓库：`nathanxiangang-web/CodeartsBridge`  
> 基线分支：`main`  
> 基线提交：`e630a197d3e043b857f1fb8e5db9749fa545045d`  
> 基线状态：v1.0.0；README 已描述 Agent Transport、Supervision、Control Center UI；当前提交说明为 855 tests passing  
> 日期：2026-09-19  
> 目标：**删除低价值功能、合并重复职责、降低配置和维护成本，让 Bridge 回到“多 Worker 高效并行开发控制器”这个核心定位。**

---

# 0. 重构结论

本轮不是继续加功能，而是明确做减法。

Bridge 当前最值得保留的主链应该只有：

```text
用户 / Architect
      ↓
Bridge Server
      ↓
Task + State + Scheduler
      ↓
AgentTransport
      ↓
Worker Agent
      ↓
CodeArts CLI
      ↓
Result / Test / Diff 自动采集
      ↓
Review
      ↓
Integration
```

旁路只保留：

```text
EventStore
Supervision
SSE / UI
Recovery
SSH fallback
```

不再继续维护“为了以后可能需要”的平台能力。

本轮重构判断标准：

> **不能直接提高派发效率、执行稳定性、查收效率、恢复能力、可观察性的代码，都要重新证明自己为什么存在。**

---

# 1. 当前复杂度盘点

当前 v1.0 已经具备：

```text
Agent Transport
SSH Transport
SSH Shell
Remote Worktree
Local Transport
Workspace Policy
Policy Engine
Timeout Policy
Runtime Supervisor
Supervision Supervisor
Agent Watchdog
Feature Flags
Shadow Mode
Architect Polling
Architect Reactor
BackgroundScheduler
CapacityMonitor
ReviewLock
Adaptive Dispatch
Cost Tracking
Telemetry
MCP
20 个 CLI 命令
10 个 Web 页面
```

单个功能看都合理，但叠加后出现三个明显问题。

## 1.1 同一职责有多套实现

典型：

```text
状态：
src/bridge/state.py
src/bridge/core/state.py

Supervisor：
src/bridge/runtime/supervisor.py
src/bridge/supervision/supervisor.py
Agent watchdog.py

Timeout：
worker timeout
agent watchdog timeout
supervision T+15
policy/timeout.py

Review 触发：
architect polling
ArchitectReactor event review
manual CLI review

Workspace：
project transport
worker transport
workspace request
workspace policy
remote-worktree transport
local-worktree workspace
```

长期维护成本会快速上升。

## 1.2 本地可信环境被过多“安全策略”限制

当前主要部署场景是：

```text
一台 Bridge 主节点
四台自己的 Worker
同一可信局域网
自己维护的项目目录
```

但代码已经引入：

```text
Policy Engine
Risk Level
Approval Gate
allowedRoots
FsGuard
secret filename blacklist
独立 review lock
workspace enforcement matrix
多 transport compatibility
```

这些很多是“平台级安全设计”，而不是当前实际场景需要。

## 1.3 迁移脚手架开始永久化

当前 supervision 仍同时存在：

```text
supervisionEnabled
supervisionShadowMode
architectEventReview
architectPollingReview
architectBackgroundEnabled
capacityEventsEnabled
```

如果继续不收敛，未来开发者会同时维护：

```text
新路径
旧路径
fallback
shadow
兼容
迁移开关
```

任何改动都需要验证多种组合。

---

# 2. 本轮目标

## 2.1 核心目标

完成后，日常开发只需要理解：

```text
Task
State
Scheduler
Agent
Supervision
Review
Integration
UI
```

## 2.2 配置目标

最终尽量只保留：

```text
projects.json
workers.json
supervision.json（后续甚至可内置默认）
```

## 2.3 代码目标

本轮明确要求：

```text
删除代码量 > 新增代码量
删除模块数 > 新增模块数
删除配置项 > 新增配置项
```

禁止为了删 A 又新造 B 抽象层。

## 2.4 运行目标

完成后必须满足：

```text
4 Worker 并发稳定
Agent 为默认主路径
Review 事件触发
15 分钟监督生效
Bridge restart 可恢复
UI 能看任务/Worker/Review/Thinking
SSH 可作为故障 fallback
```

---

# 3. 明确保留的核心

## 3.1 Agent Transport

保留：

```text
src/bridge/transport/agent.py
src/bridge/agent/*
```

因为它解决了：

```text
长 SSH 会话
任务恢复
事件回传
本地执行
hard timeout
```

## 3.2 EventStore

保留：

```text
src/bridge/core/events.py
src/bridge/state_events.py
```

保留能力：

```text
append-only
seq cursor
rotation
flock
```

## 3.3 Supervision 核心

保留：

```text
schedule.py
supervisor.py
inspector.py
reactor.py
```

这是 5/3/3/2/2/1 的核心。

## 3.4 Review / Integration

保留：

```text
application/review_service.py
integration
```

但要减少重复入口和重复锁。

## 3.5 UI

保留控制中心，但页面收敛。

最终核心页面：

```text
Dashboard
Tasks
Task Detail + DAG
Workers
Review
Thinking
Settings + Projects
```

---

# 4. 第一批直接删除：Policy Engine

删除：

```text
src/bridge/policy/engine.py
src/bridge/policy/runtime.py
src/bridge/policy/integration.py
src/bridge/policy/timeout.py
src/bridge/policy/__init__.py
```

同步删除相关测试与文档。

## 4.1 原因

当前任务已经存在：

```text
TASK.md
验收标准
Worker 测试
Review
Integration verification
```

Policy 又增加：

```text
riskLevel
requiresApproval
approvalGate
preCheck
postCheck
onFailure
requiredEvidence
phase
check
```

收益和现有流程重叠。

## 4.2 worker.py 修改

删除 import：

```python
from .policy.integration import (
    load_profile_for_project,
    evaluate_pre_checks,
    evaluate_task_policy,
    should_block_task,
    should_transition_to_review,
)
```

删除：

```python
policy_profile = load_profile_for_project(...)
```

删除 preCheck 整段。

删除 postCheck 整段。

完成后主流程：

```text
Worker 完成
  ↓
检查交付物
  ↓
REVIEW_REQUIRED
```

若任务明确：

```text
review.required=false
```

则：

```text
DONE
```

## 4.3 替代

项目真正需要测试门禁时，优先放到：

```text
TASK.md
verifyCommand
Review
```

不要维护 Policy DSL。

---

# 5. Workspace 做减法

当前用户面：

```text
auto
isolated
existing
worktree
local-worktree
remote-worktree
shared-readonly
```

最终只保留：

```text
existing
worktree
```

可选保留：

```text
auto
```

但仅作为默认别名。

## 5.1 删除用户可选模式

删除：

```text
isolated
local-worktree
remote-worktree
shared-readonly
```

内部实现可以继续复用 worktree helper，但不要暴露多套语义。

## 5.2 最终规则

```text
workspace=existing
    Agent 直接 cwd=projectRoot

workspace=worktree
    创建 git worktree
```

默认：

```text
Agent -> existing
```

只有确实需要同一仓库并行写时才选：

```text
worktree
```

## 5.3 修改文件

```text
src/bridge/workspace/policy.py
src/bridge/application/task_service.py
src/bridge/cli.py
src/bridge/worker.py
```

CLI 从：

```text
--workspace-mode auto|isolated|existing|worktree|local-worktree|remote-worktree|shared-readonly
```

收敛为：

```text
--workspace existing|worktree
```

---

# 6. Transport 收敛

当前：

```text
local
ssh
ssh-shell
remote-worktree
agent
```

最终：

```text
agent     # 主路径
ssh       # break-glass fallback
local     # 测试/本机调试
```

## 6.1 用户配置先删除

不再允许新配置使用：

```text
ssh-shell
remote-worktree
```

## 6.2 两阶段删除

第一阶段：

```text
保留实现文件
README 不展示
新配置禁止生成
标记 deprecated
```

第二阶段稳定后删除：

```text
src/bridge/transport/ssh_shell.py
src/bridge/transport/remote_worktree.py
src/bridge/workspace/remote_worktree.py
```

## 6.3 TRANSPORT_MAP 最终

```python
TRANSPORT_MAP = {
    "agent": AgentTransport,
    "ssh": SshTransport,
    "local": LocalTransport,
}
```

生产部署文档只推荐：

```text
agent
```

---

# 7. Agent 安全功能减法

本轮不是完全无安全，而是只保留真正有价值、几乎不增加使用摩擦的部分。

## 7.1 删除 allowedRoots

当前安装脚本生成：

```json
{
  "allowedRoots": ["/home/nathan/bridge-python"]
}
```

每增加一个项目都要修改每台 Worker，实际很烦。

删除：

```text
AgentConfig.allowed_roots
AgentConfig.is_project_allowed()
```

删除 Agent 创建 job 时的 root allowlist check。

新行为：

```text
projectRoot 存在 -> cwd 执行
projectRoot 不存在 -> 明确报错
```

## 7.2 删除 fs_guard.py

删除：

```text
src/bridge/agent/fs_guard.py
```

Agent 不是通用远程文件服务器，主执行路径本来就是 CodeArts CLI cwd。

不再维护：

```text
.env blacklist
.ssh blacklist
token filename blacklist
```

## 7.3 Token 简化

现在四 Worker：

```text
BRIDGE_AGENT_W01_TOKEN
BRIDGE_AGENT_W02_TOKEN
BRIDGE_AGENT_W03_TOKEN
BRIDGE_AGENT_W04_TOKEN
```

改成一个：

```text
BRIDGE_CLUSTER_TOKEN
```

四台共用。

workers.json 删除：

```text
agentTokenEnv
```

## 7.4 可选 trusted LAN

允许：

```text
--no-auth
```

或：

```text
BRIDGE_AGENT_AUTH=off
```

可信内网可以直接关闭认证。

默认仍建议使用一个 cluster token。

不引入：

```text
OAuth
JWT
RBAC
mTLS
用户系统
ACL
```

---

# 8. Agent inflight 做减法

当前 `inflight.json` 包含 token。

改成只保存：

```json
{
  "jobId": "...",
  "endpoint": "..."
}
```

恢复时从：

```text
BRIDGE_CLUSTER_TOKEN
```

重新读取。

删除：

```text
token persistence
per-task secret handling
```

---

# 9. Supervision 收敛

最终只保留：

```text
schedule.py
supervisor.py
inspector.py
reactor.py
```

## 9.1 删除 FeatureFlags

删除：

```text
src/bridge/supervision/flags.py
```

固定最终行为：

```text
supervision = ON
event review = ON
polling review = OFF
```

## 9.2 删除 Shadow Mode

删除配置：

```text
supervisionShadowMode
```

## 9.3 删除 Architect Polling

删除：

```text
architectPollingReview
```

pipeline 不再主动：

```python
architect_loop(...)
```

唯一正常 review 触发：

```text
RUNNING
  ↓
REVIEW_REQUIRED
  ↓
EventStore
  ↓
ArchitectReactor
```

## 9.4 删除 BackgroundScheduler

删除：

```text
src/bridge/supervision/background.py
```

当前先把主链跑满，不急着优化 Architect 碎片时间。

## 9.5 删除 CapacityMonitor

删除：

```text
src/bridge/supervision/capacity.py
```

任务提前规划放回 Architect 正常规划过程，不再额外维护 `capacity.available` 入口。

## 9.6 删除 ReviewLock

删除：

```text
src/bridge/supervision/review_lock.py
```

替代：

```text
ArchitectQueue dedupe
+
review 前检查 state == REVIEW_REQUIRED
```

单 Reactor 足够。

---

# 10. 合并双 Supervisor

当前：

```text
src/bridge/runtime/supervisor.py
src/bridge/supervision/supervisor.py
src/bridge/agent/watchdog.py
```

最终职责重新分配。

## 10.1 Worker Agent Watchdog

只负责：

```text
进程是否活着
soft timeout
hard timeout
kill
job local recovery
```

## 10.2 Bridge Supervisor

只负责：

```text
5/8/11/13/15/16
进度判断
状态收敛
触发 Architect
```

## 10.3 删除 runtime/supervisor.py

其职责迁移到：

```text
Agent Recovery
Supervision startup reconcile
AgentTransport inflight resume
```

删除前必须先验证重启恢复完整。

---

# 11. 合并双 State

当前：

```text
src/bridge/state.py
src/bridge/core/state.py
```

最终只保留：

```text
src/bridge/core/state.py
```

## 11.1 迁移顺序

1. 全局找 `from bridge.state import ...`
2. 全部迁到 `bridge.core.state`
3. 把 legacy timestamp/revision 能力合进去
4. 跑全测试
5. 删除 `src/bridge/state.py`
6. 删除 legacy state test

## 11.2 状态机继续做减法

优先保留：

```text
READY
RUNNING
REVIEW_REQUIRED
FIX_REQUIRED
DONE
FAILED
ASSISTANCE_REQUIRED
CANCELLED
```

按真实需要保留：

```text
QUEUED
STARTING
INTEGRATING
CONFLICT
```

不再轻易增加新状态。

---

# 12. Scheduler 做减法

当前四 Worker：

```text
同模型
相似 capabilities
concurrencyLimit=1
```

不需要复杂 scoring。

## 12.1 保留

```text
dependency
capacity
lease
review anti-affinity
```

## 12.2 弱化或删除

```text
复杂 score_worker
Agent host affinity
多层 preferred fallback
复杂 skill ranking
```

Agent Scheduler 只需：

```text
enabled
capacity available
supports role
```

然后：

```text
round-robin
```

或：

```text
least-loaded
```

即可。

---

# 13. 删除 Adaptive Dispatch

删除：

```text
src/bridge/adaptive.py
bridge adaptive-dispatch
```

删除相关测试和 README。

超时与调度参数先固定，四个 Worker 没必要再引入遥测自动调参。

---

# 14. 删除 Cost Tracking

删除：

```text
src/bridge/cost.py
bridge cost
/api/cost
cost_rates.json
UI cost 展示
```

保留真正有价值的：

```text
tokens
duration
timeout rate
retry rate
```

这些属于 telemetry，不属于计费系统。

---

# 15. Telemetry 简化

保留：

```text
task duration
success rate
timeout rate
retry rate
worker utilization
review latency
dispatch latency
```

删除：

```text
角色成本
项目成本
估算费用
复杂成本聚合
```

---

# 16. MCP 默认关闭或拆出

当前 `bridge serve` 默认还启动 MCP thread。

改成：

```text
bridge serve
```

只启动：

```text
HTTP API
UI
SSE
Supervisor
ArchitectReactor
Dispatcher
```

如果 MCP 真实还在用：

```text
bridge mcp
```

独立启动。

如果近期完全不用：

```text
删除 src/bridge/interfaces/mcp
```

---

# 17. CLI 做减法

当前 README 列了 20 个 CLI。

最终目标约 8 个：

```text
bridge serve
bridge doctor
bridge status
bridge create
bridge dispatch
bridge cancel
bridge retry
bridge integrate
```

可选保留：

```text
bridge bootstrap
```

## 17.1 删除用户入口

删除：

```text
auto-dispatch
adaptive-dispatch
cost
telemetry
projects
workers
pause
resume
review-pass
review-fix
pipeline
```

其中底层能力不一定全部删除，但不再作为用户日常入口。

## 17.2 UI 成为主管理面

以下功能统一从 UI 做：

```text
Projects
Workers
Review
Retry
Pause
Metrics
```

不要长期同时维护：

```text
CLI 管理面
Web 管理面
MCP 管理面
```

三套入口。

---

# 18. UI 做减法

当前 10 页面。

最终：

```text
1. Dashboard
2. Tasks
3. Task Detail + DAG
4. Workers
5. Review
6. Thinking
7. Settings + Projects
```

## 18.1 合并

```text
Metrics -> Dashboard
DAG -> Task Detail
Projects -> Settings
```

## 18.2 页面重点

只回答：

```text
谁在干活
干到哪
谁卡住了
谁完成了
谁要 review
错误是什么
下一步是什么
```

避免继续增加低价值统计页。

---

# 19. Worker 交付物做减法

当前通常要求：

```text
RESULT.md
TESTS.md
DIFF.stat
DIFF.patch
```

改为最多：

```text
RESULT.md
TESTS.md
```

甚至可以最终只保留：

```text
RESULT.md
```

## 19.1 Diff 自动生成

Bridge / Agent 自动：

```text
git status
git diff --stat
git diff
changed files
```

AI 不再花时间手写：

```text
DIFF.stat
DIFF.patch
```

## 19.2 RESULT.md 建议格式

```markdown
# Result

## 完成
- ...

## 测试
- pytest ...
- pass

## 风险
- 无
```

---

# 20. projects.json 做减法

当前 projects.json 存在大量：

```text
cloudsite-rc1-w01
cloudsite-rc1-w02
cloudsite-rc1-w03
cloudsite-rc1-w04
bus-rc1-w01
...
bridge-dev-w01
...
```

本质是：

```text
项目 × Worker
```

Agent 化后应删除。

## 20.1 新结构

```json
{
  "projects": [
    {
      "id": "bridge",
      "projectRoot": "/home/nathan/bridge-python"
    },
    {
      "id": "cloudsite",
      "projectRoot": "/home/nathan/CloudSite"
    }
  ]
}
```

Project 不再绑定 host。

Scheduler 决定任务去哪台 Worker。

---

# 21. workers.json 做减法

当前字段很多：

```text
transport
host
endpoint
agentTokenEnv
cliPath
model
concurrencyLimit
enabled
capabilities
```

最终建议：

```json
{
  "workers": [
    {
      "id": "w01",
      "endpoint": "http://192.168.178.52:8765",
      "enabled": true
    }
  ]
}
```

Agent health 自己报告：

```text
cliPath
capacity
version
hostname
```

全局 model 从一处配置即可。

---

# 22. supervision.json 做减法

当前多个迁移开关。

最终：

```json
{
  "offsetsSeconds": [300,480,660,780,900,960],
  "heartbeatStaleSeconds": 90,
  "noProgressThreshold": 2,
  "repeatedErrorThreshold": 3
}
```

第二阶段甚至可以完全删除此文件，使用代码默认。

---

# 23. README 做减法

README 只保留：

```text
1. 项目是什么
2. 快速启动
3. projects.json
4. workers.json
5. bridge serve
6. Web UI
7. 故障排查
```

不要首页继续展示：

```text
20 CLI
5 Transport
Policy DSL
全部内部状态
全部内部 API
```

内部内容移到：

```text
docs/internal/
```

---

# 24. 第一阶段直接删除清单

低风险优先：

```text
src/bridge/policy/*
src/bridge/agent/fs_guard.py
src/bridge/supervision/background.py
src/bridge/supervision/capacity.py
src/bridge/supervision/flags.py
src/bridge/supervision/review_lock.py
src/bridge/adaptive.py
src/bridge/cost.py
```

同步删除配置：

```text
riskLevel
approvalGate
allowedRoots
agentTokenEnv per worker
adaptive config
cost_rates.json
background flags
capacity flags
shadow flags
```

---

# 25. 第二阶段合并清单

```text
state.py -> core/state.py
runtime/supervisor.py -> supervision + Agent recovery
workspace matrix -> existing/worktree
project-per-worker profile -> project-only config
```

---

# 26. 第三阶段删除兼容层

稳定后删除：

```text
ssh-shell
remote-worktree
architect polling
legacy supervision flags
legacy workspace aliases
旧 project profiles
```

SSH 只保留：

```text
break-glass fallback
```

---

# 27. 开发波次

## Wave 0：冻结新功能

本轮规则：

```text
不新增功能
除修 bug 外不得增加新模块
```

建立基线：

```text
pytest
Playwright
4 Worker Agent smoke
Bridge restart smoke
Agent restart smoke
```

## Wave 1：无行为变化删除

先删：

```text
adaptive
cost
unused security helper
background
capacity
flags
```

核心 E2E 必须不变。

## Wave 2：Policy 拆除

重点修改：

```text
worker.py
tests
README
配置
```

必须验证：

```text
Task -> Agent -> Result -> REVIEW_REQUIRED
```

## Wave 3：Workspace / Transport 收敛

目标：

```text
Agent existing workspace
可选 worktree
SSH fallback
```

项目配置不再 per-worker。

## Wave 4：Supervision 收敛

切换：

```text
ArchitectReactor ON
Architect Polling OFF
```

稳定后删除迁移代码。

## Wave 5：State / Supervisor 合并

高风险，必须单独一波。

## Wave 6：CLI / UI / Docs 减法

最后处理用户面，不与核心执行链同时修改。

---

# 28. 四人分工

## W01 — Policy / Agent Cleanup

负责：

```text
删除 policy
删除 fs_guard
简化 Agent auth
简化 inflight token
```

验收：

```text
Agent 任务正常
Review 正常
Recovery 正常
```

## W02 — Workspace / Transport Cleanup

负责：

```text
workspace existing/worktree
停止暴露 remote-worktree
停止暴露 ssh-shell
projects.json 合并
```

## W03 — Supervision / State Cleanup

负责：

```text
Event Review ON
Polling OFF
删除 flags/shadow/review lock
规划 state 合并
```

## W04 — UI / CLI / Regression

负责：

```text
删低价值 CLI
页面合并
README
全量测试
真实 E2E
```

---

# 29. 填坑清单

## 坑 1：删 Policy 后测试门禁一起没了

真正必要的 verify 必须迁移到：

```text
Task
Review
Integration verify
```

不能只删不迁。

## 坑 2：Agent transport 与 project.transport 混用

当前 Worker 可能：

```text
执行 transport 看 worker.transport
workspace policy 看 project.transport
```

必须新增一个简单变量：

```text
effective_transport
```

后续判断统一用它。

## 坑 3：删除 remote-worktree 后并行冲突

保留一个：

```text
worktree
```

解决真正需要的隔离。

## 坑 4：旧 projectId 迁移

旧任务可能引用：

```text
bridge-dev-w01
bridge-dev-w03
```

需要一个版本兼容映射：

```text
bridge-dev-w01 -> bridge
bridge-dev-w03 -> bridge
```

## 坑 5：Cluster Token 同步

部署脚本必须自动：

```text
生成一次
同步四台 Worker
Bridge 同步读取
```

不能重新变成人工复制。

## 坑 6：关闭 Polling 后事件漏发导致永远不 review

正式关闭前必须证明：

```text
RUNNING -> REVIEW_REQUIRED
必有 event
```

同时 startup 做一次 recovery scan：

```text
扫描 REVIEW_REQUIRED
补进 ReactorQueue
```

注意：

```text
只在启动时扫描
不是持续 polling
```

## 坑 7：删除 ReviewLock 后双消费

要求：

```text
单 Reactor consumer
Queue dedupe
review 前再次检查 state
```

## 坑 8：删除 Feature Flag 后不好回滚

回滚使用 Git / commit，不再长期维护 6 个 runtime 开关。

可以临时保留一个：

```text
legacyPollingReview
```

只保留一个版本。

## 坑 9：State 合并不能和其他大改一起做

必须独立 commit / 独立 wave。

## 坑 10：Runtime Supervisor 删除后恢复链断裂

删除前验证职责已落到：

```text
Agent Recovery
Supervision startup reconciliation
AgentTransport inflight resume
```

## 坑 11：删除 cost 后 API / UI 残留

全局搜索：

```text
/api/cost
cost()
Cost
cost_rates
```

同步删除。

## 坑 12：CLI 删除后脚本还调用旧命令

全局检查：

```text
install.sh
deploy.sh
README
docs
tests
```

## 坑 13：allowedRoots 删除后 health 逻辑错误

当前 Agent health 里存在把：

```text
allowed_roots[0]
```

当成 `codearts.path` 的错误语义。

改成：

```text
shutil.which("codearts")
```

或真实 `cliPath`。

## 坑 14：Agent 无 token 时随机生成但 Bridge 不知道

禁止：

```text
运行时随机生成且不持久化
```

只允许：

```text
BRIDGE_CLUSTER_TOKEN
或 auth off
```

## 坑 15：UI 路由合并后旧链接失效

保留一版 redirect：

```text
#metrics -> #dashboard
#dag/<id> -> #task-detail/<id>
#projects -> #settings
```

## 坑 16：交付物减少后 Completion 判定仍要求 3 文件

统一修改所有判断。

旧：

```text
RESULT + TESTS + DIFF.stat
```

新：

```text
RESULT + TESTS
```

或最终：

```text
RESULT
```

## 坑 17：自动 diff 失败不能让任务失败

规则：

```text
Result 完成
测试完成
diff capture 失败 -> warning
```

不能因此把任务设为 FAILED。

## 坑 18：Scheduler 简化后 anti-affinity 丢失

仍保留：

```text
Reviewer != Implementer
```

这是高价值约束。

## 坑 19：MCP 删除影响真实外部集成

先确认使用情况。

如果有人用，改为：

```text
bridge mcp
```

独立启动。

## 坑 20：一口气删太多无法定位回归

每 Wave：

```text
独立 commit
独立 pytest
独立 smoke
```

禁止一个 commit 删除 20 个系统。

## 坑 21：Agent health / capacity 由哪边配置

简化后优先让 Worker 自报：

```text
version
hostname
cliPath
capacity
activeJobs
```

Bridge 不重复维护。

## 坑 22：Project Root 多机不一致

如果四台 Worker 路径不同，不要重新回到 per-worker project profile。

建议 workers.json 允许一个非常小的 override：

```json
{
  "projectRoots": {
    "bridge": "/root/bridge-python"
  }
}
```

只有有差异的 Worker 才配置。

## 坑 23：SSH fallback 与 Agent 配置混在一起

SSH fallback 配置不应污染正常 workers.json。

可独立：

```text
fallbackSshHost
```

仅 doctor / recovery 使用。

## 坑 24：删 telemetry 过头

不要删掉真正衡量效率的数据：

```text
Worker utilization
Task duration
Timeout rate
Review latency
```

本轮删的是“成本核算”和低价值统计，不是观测能力。

---

# 30. 测试矩阵

每一 Wave 都跑：

```text
pytest
tests/agent
tests/supervision
tests/ui
```

真实 Smoke：

```text
W01 Agent health
W02 Agent health
W03 Agent health
W04 Agent health
```

主链：

```text
create
  ↓
dispatch
  ↓
RUNNING
  ↓
REVIEW_REQUIRED
  ↓
review
  ↓
DONE
```

异常链：

```text
timeout
cancel
Agent restart
Bridge restart
Worker offline
```

---

# 31. 真实验收任务

## Task A：普通修改

```text
修改一个 Python 函数
增加一个测试
```

验收：

```text
Agent 执行
无需 SSH
无需 Policy
无需 Approval Gate
正常 Review
```

## Task B：测试失败

制造一个失败测试。

验收：

```text
ASSISTANCE_REQUIRED / FIX_REQUIRED
```

不再经过 Policy BLOCKED。

## Task C：15 分钟 timeout

验收：

```text
Agent kill
Supervisor 收敛
Diff salvage
Architect 收到事件
```

## Task D：Bridge restart

验收：

```text
inflight 恢复
task 文件不保存 token
```

## Task E：4 Worker 并发

四个独立任务同时派发。

验收：

```text
4 Worker 同时 RUNNING
各自独立 5/8/11/13/15/16
提前完成即时 Review
```

---

# 32. 删除规模目标

建议明确工程指标：

```text
生产代码净减少 20%~30%
配置字段减少 40%+
用户可见 CLI 减少 50%+
Transport 用户选项减少 40%+
Workspace 用户选项减少 60%+
Supervision Feature Flags 减少 100%
```

测试数量不追求同比减少。

原则：

```text
删功能 -> 可以删对应测试
核心 E2E -> 反而加强
```

---

# 33. 最终目录目标

```text
src/bridge/
├── api/
├── application/
├── core/
│   ├── state.py
│   ├── events.py
│   └── models.py
├── agent/
│   ├── server.py
│   ├── runner.py
│   ├── watchdog.py
│   ├── recovery.py
│   └── store.py
├── transport/
│   ├── agent.py
│   ├── ssh.py
│   └── local.py
├── supervision/
│   ├── schedule.py
│   ├── supervisor.py
│   ├── inspector.py
│   └── reactor.py
├── scheduler/
├── workspace/
│   ├── existing.py
│   └── worktree.py
├── integration/
├── web/
├── config.py
├── worker.py
└── cli.py
```

不再存在：

```text
policy/
adaptive.py
cost.py
supervision/flags.py
supervision/background.py
supervision/capacity.py
supervision/review_lock.py
transport/ssh_shell.py
transport/remote_worktree.py
workspace/remote_worktree.py
legacy state.py
runtime supervisor duplication
```

---

# 34. 最终配置目标

## workers.json

```json
{
  "workers": [
    {
      "id": "w01",
      "endpoint": "http://192.168.178.52:8765",
      "enabled": true
    },
    {
      "id": "w02",
      "endpoint": "http://192.168.178.50:8765",
      "enabled": true
    },
    {
      "id": "w03",
      "endpoint": "http://192.168.178.53:8765",
      "enabled": true
    },
    {
      "id": "w04",
      "endpoint": "http://192.168.178.51:8765",
      "enabled": true
    }
  ]
}
```

## projects.json

```json
{
  "projects": [
    {
      "id": "bridge",
      "projectRoot": "/home/nathan/bridge-python"
    },
    {
      "id": "cloudsite",
      "projectRoot": "/home/nathan/CloudSite"
    }
  ]
}
```

Bridge 不再要求用户理解：

```text
sshHost
remoteBridgeRoot
remoteWorkspaceRoot
remoteCliPath
riskLevel
workspace matrix
agentTokenEnv
```

---

# 35. Definition of Done

```text
[ ] Policy Engine 完全删除
[ ] Policy 不再出现在 worker.py
[ ] allowedRoots 删除
[ ] fs_guard 删除
[ ] Agent token 简化为 cluster token 或 auth off
[ ] inflight.json 不再保存 token
[ ] workspace 用户面只剩 existing/worktree
[ ] Agent 成为默认 transport
[ ] ssh-shell 不再暴露
[ ] remote-worktree 不再暴露
[ ] Event Review 正式开启
[ ] Architect Polling 正式关闭
[ ] supervision shadow/feature flags 删除
[ ] BackgroundScheduler 删除
[ ] CapacityMonitor 删除
[ ] ReviewLock 删除
[ ] 双 State 合并
[ ] 双 Supervisor 收敛
[ ] adaptive-dispatch 删除
[ ] cost 删除
[ ] CLI 命令缩减到约 8 个
[ ] UI 页面缩减到 6~7 个
[ ] Projects 不再 per-worker 建 profile
[ ] Worker 不再手写 DIFF.patch / DIFF.stat
[ ] 4 Worker Agent smoke 全通过
[ ] Bridge restart 可恢复
[ ] Agent restart 可恢复
[ ] REVIEW_REQUIRED 可事件触发
[ ] T+15 timeout 可自动收敛
[ ] pytest 全通过
[ ] Playwright E2E 全通过
```

---

# 36. 本轮禁止事项

为了避免“做减法又做成新平台”，本轮明确禁止：

```text
禁止新增新的 Policy DSL
禁止新增新的 Transport
禁止新增新的 Workspace mode
禁止新增新的 Feature Flag
禁止新增新的 Task State，除非现有状态无法表达
禁止新增新的安全抽象层
禁止新增新的配置文件
禁止因为删除模块而新造 Facade/Manager/Coordinator 层
禁止同时重写核心执行链和 UI
```

每个 PR 必须回答：

```text
这次净删了多少？
减少了几个配置？
减少了几个分支？
是否让主链更短？
```

---

# 37. 最终判断标准

以后新增任何功能前必须回答三个问题：

```text
1. 这个功能是否直接提高 Worker 并行效率？
2. 是否直接提高失败恢复或查收效率？
3. 如果没有它，真实日常使用会不会明显变差？
```

三个都是否：

```text
不加。
```

如果只是：

```text
更安全
更通用
更像平台
以后可能用
企业级
```

但当前真实使用没有收益：

```text
先不做。
```

---

# 38. 最终定位

CodeartsBridge 不应该变成：

```text
通用 AI Agent 企业控制平台
```

它应该是：

```text
一个简单、直接、能把 4 个 Worker 真正跑满的 AI 开发调度器
```

理想状态：

```text
配置两份 JSON
bridge serve
打开网页
创建任务
4 个 Worker 并行干活
完成自动触发 Review
卡住自动报警
15 分钟自动收敛
Bridge 重启还能接回来
```

除此之外的复杂度，都应该非常谨慎地增加。

> **这轮重构的成功，不是“功能更多”，而是“删掉一半之后，开发反而更快、更稳、更容易理解”。**
