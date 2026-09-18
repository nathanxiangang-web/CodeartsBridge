# CodeartsBridge 持续开发推进文档

> 用途：作为 CodeartsBridge 项目的 AI 持续开发主文档。  
> 后续 Architect AI / Worker AI 每次开始工作时，应优先读取本文件，并以本文件作为当前整改阶段、职责边界、依赖关系和验收标准的主要依据。  
> 当前目标：**先完成 P0 控制面收口，再进入 P1 高效率开发优化。**

---

# 1. 项目当前定位

CodeartsBridge 当前不应继续向“大型 AI 开发平台”扩张。

它的核心定位是：

> **一个面向多 AI 软件开发的轻量级任务控制平面。**

主要职责：

- 接收 Architect AI 生成的工程任务。
- 根据依赖、Worker 能力、主机、工作区和并发情况进行调度。
- 将任务交给 CodeArts / GLM Worker。
- 管理运行状态、进程、超时、取消、重试和证据。
- 使用独立 worktree / remote workspace 保证多 Worker 并行时不互相污染。
- 收集 Patch、测试、Diff、Checkpoint、Blocker。
- 交回 Architect AI Review 和集成。

核心链路：

```text
User
 ↓
Architect AI
 ↓
Task DAG
 ↓
CodeartsBridge
 ↓
Dispatcher / Daemon
 ↓
W01 / W02 / W03 / W04
 ↓
Patch + Tests + Evidence
 ↓
QA / Architect Review
 ↓
Integration
 ↓
Main
```

核心原则：

> AI 决定 WHAT。  
> Bridge 决定 WHEN / WHERE / PROCESS。  
> Worker 决定 HOW。

---

# 2. 当前代码基线

当前审查基线：

```text
Repository: nathanxiangang-web/CodeartsBridge
Branch: main
Baseline Commit:
84cd72c3e40b3bc343a8bc4dfe513e536e331324
```

当前 Python 主体位于：

```text
src/bridge/
```

主要模块：

```text
atomic.py
locks.py
config.py
state.py
task.py
dispatch.py
worker.py
daemon.py
codearts.py
git_ops.py
cli.py
progress.py

transport/
policy/
```

当前已有主要能力：

- Task 创建。
- READY → QUEUED → STARTING → RUNNING → REVIEW_REQUIRED → DONE 状态基础。
- Worker Registry。
- Project Registry。
- Worker capability。
- Worker concurrencyLimit。
- dependsOn。
- local transport。
- ssh transport。
- ssh-shell transport。
- remote-worktree transport。
- Git bundle / worker result ref。
- CodeArts session reuse。
- daemon。
- policy engine 基础代码。
- task inbox / outbox / evidence。
- atomic write。
- file lock。
- Architect / Worker protocol。
- Python 测试 67 个。

---

# 3. 当前开发总目标

现阶段不要继续堆大量新能力。

当前最高优先级：

```text
① 调度可靠
② Worker 真正隔离
③ 进程生命周期可控
④ 状态语义统一
⑤ AI 职责固定
⑥ 上下文最小化
⑦ 多 Worker 持续高利用率
```

阶段路线：

```text
P0：可信控制面
 ↓
P1：高效率调度与上下文优化
 ↓
P2：AI 自动开发流水线
 ↓
P3：数据驱动优化
```

**P0 未完成前，不进入大规模 P1 功能开发。**

---

# 4. AI 职责划分

## 4.1 User

用户只负责：

- 提出需求。
- 确定业务优先级。
- 决定重大架构冲突。
- 最终发布确认。

用户不应参与：

- 普通 lint。
- 普通 test 修复。
- 路径错误。
- 小范围代码实现。
- Worker 普通 retry。
- 常规依赖问题。

目标：

> 不让用户成为 AI 流水线中的同步阻塞点。

---

## 4.2 Architect AI

负责：

- 理解需求。
- 分析项目。
- 维护架构。
- 维护本开发文档。
- 拆分 Task。
- 建立 Task DAG。
- 指定验收标准。
- 指定 Worker。
- 处理 Architectural Blocker。
- Review Worker 结果。
- 控制集成顺序。
- 做跨模块回归。
- 决定是否进入下一阶段。

Architect AI **不要长期承担具体实现代码**。

Architect 的核心 KPI：

> 保证 Worker 始终有正确、足够小、可独立验收的任务可以执行。

---

## 4.3 Bridge

Bridge 不是 AI。

Bridge 负责确定性控制：

```text
task queue
dependency
worker resource
host affinity
workspace isolation
lock
lease
process
timeout
cancel
retry
quota state
git refs
evidence
telemetry
state
```

原则：

> 可以用确定性程序解决的事情，不让 AI 决定。

---

## 4.4 W01 — Runtime Worker

长期模块所有权：

```text
daemon
process supervisor
runtime
transport runtime
timeout
cancel
process lifecycle
```

W01 主要负责运行时。

---

## 4.5 W02 — State & Quality Logic Worker

长期模块所有权：

```text
state
task lifecycle
attempt
result classifier
worker result semantics
model routing logic
quality state mapping
```

W02 负责状态和结果语义。

---

## 4.6 W03 — Scheduler & Resource Worker

长期模块所有权：

```text
dispatch
worker registry
resource model
worker-host affinity
priority
health
scheduler
quota-aware scheduling
```

W03 负责调度和资源。

---

## 4.7 W04 — QA Worker

W04 不作为普通实现 Worker 使用。

主要职责：

```text
review
test
regression
E2E
CI
acceptance
edge cases
protocol consistency
```

原则：

> 写代码的 Worker 不负责证明自己完全正确。

W04 要独立验收 W01 / W02 / W03 的实现。

---

# 5. Worker 通用开发规则

每个 Worker Task 必须满足：

- 一个主要交付物。
- 一个主要故障域。
- 可独立测试。
- 可独立 Review。
- 尽量 10 分钟左右完成。
- 默认 hard timeout 不超过 15 分钟。
- Required Changes 尽量不超过 5 项。
- 不允许顺手扩展无关模块。
- 不允许同时修改多个核心边界。
- FIX 只能修当前交付物的窄缺陷。
- 新模块或新阶段必须创建新 Task。
- Worker 不决定公共 API、数据库 Schema、核心架构。
- 遇到架构冲突交回 Architect。

Worker 正常执行循环：

```text
SEARCH
 ↓
READ
 ↓
EDIT
 ↓
TEST
 ↓
ANALYZE
 ↓
EDIT
 ↓
TEST
 ↓
DELIVER
```

正式交付必须包含：

```text
RESULT.md
DIFF.stat
TESTS.md
DIFF.patch
```

时间不足时：

```text
CHECKPOINT.md
ASSISTANCE_REQUEST.md
```

架构问题：

```text
BLOCKER.md
```

---


## 5.1 UI / 回显可靠性专项规则

UI 回显属于 P0 可靠性问题，不按普通界面优化处理。

当前代码审查已经确认：

```text
CodeArts CLI
 ↓
transport subprocess.run(capture_output=True)
 ↓
等待进程结束
 ↓
一次性获得 stdout/stderr
 ↓
parse_codearts_json_lines()
 ↓
最终更新 state.json
```

当前运行过程中缺少稳定的实时事件生产链。

同时：

- `progress.py` 主要依赖轮询 `state.json`。
- `state.py` 虽然定义了 `lastHeartbeat`、`heartbeatSummary`、`heartbeatEvents` 等字段，但当前 Worker 执行链没有稳定持续更新这些字段。
- daemon 后台启动 `bridge run` 时把 launcher stdout/stderr 指向 `DEVNULL`。
- `progress.py` 即使每 5 秒刷新，如果 state 中没有新的 heartbeat，也只能显示旧状态或空白摘要。
- CodeArts JSONL 当前主要是在 Worker 结束后一次性解析，而不是运行中增量解析。

因此“经常不回显”不能只通过修改 UI 刷新频率解决。

必须修复：

```text
事件产生
 ↓
事件持久化
 ↓
heartbeat/state snapshot
 ↓
UI 消费
 ↓
断线恢复
```

UI 回显必须遵守以下原则：

1. **运行中必须有持续 heartbeat。**
2. **状态变化必须立即产生可消费事件。**
3. **UI 晚打开也不能是空白，必须能读到当前 snapshot 和最近事件。**
4. **UI 重启/刷新后必须恢复显示，不依赖内存中的瞬时消息。**
5. **四个 Worker 并发时事件必须按 taskId/attempt 隔离。**
6. **终态必须立即回显，不允许 Worker 已结束但 UI 仍长期显示 RUNNING。**
7. **UI 卡住不能影响 Worker 执行。**
8. **Worker 卡住不能让 UI 假装任务正常。**
9. **UI 应显示 STALE，而不是把“长时间无事件”直接判成 FAILED。**
10. **不得把模型私有 reasoning / chain-of-thought 原样展示到 UI。**
11. **回显内容只允许高层事件摘要、工具动作、测试状态、警告和最终状态。**
12. **任何可能包含凭据的输出在进入 UI 事件流前必须先做敏感信息遮盖。**

建议形成统一事件模型：

```json
{
  "seq": 123,
  "timestamp": "UTC ISO8601",
  "taskId": "task-id",
  "attempt": 1,
  "workerId": "w01",
  "type": "heartbeat|status|tool|test|warning|terminal",
  "summary": "safe high-level summary"
}
```

推荐持久化：

```text
tasks/<task-id>/runtime/events.jsonl
```

`state.json` 保存最新快照：

```text
lastEventAt
lastHeartbeat
heartbeatSummary
heartbeatEvents
processId
status
attempt
```

事件流负责“发生过什么”。

state snapshot 负责“现在是什么”。

不要用一个字段同时承担两个职责。

---

# 6. P0 — 可信控制面整改

---

## P0-01
# control-plane: unify CLI and daemon dispatch execution semantics

负责人：

```text
W01
```

依赖：

```text
无
```

主要范围：

```text
cli.py
daemon.py
dispatch execution service
```

问题：

当前 `bridge dispatch` 会把 READY 任务改成 QUEUED，但不会启动 Worker。

daemon 则拥有另一套实际 spawn Worker 的逻辑。

这会导致 CLI / daemon 行为不一致，并可能造成任务永久 QUEUED。

目标：

建立唯一 Dispatch Execution Service。

目标流程：

```text
plan
 ↓
claim task
 ↓
QUEUED
 ↓
spawn Worker
 ↓
return dispatch result
```

CLI 与 daemon 必须调用同一实现。

验收标准：

- `bridge dispatch` 能真正启动 Worker。
- daemon 调用同一个 dispatch service。
- `--dry-run` 不修改 state。
- `--dry-run` 不启动 Worker。
- spawn 失败不能留下永久 QUEUED。
- 同一任务并发 dispatch 最多 spawn 一次。
- 增加 CLI dispatch E2E 测试。
- README Quick Start 和实际行为一致。

完成状态：

```text
TODO
```

---

## P0-02
# state: persist attempt lifecycle and prevent evidence/log overwrite

负责人：

```text
W02
```

依赖：

```text
无
```

主要范围：

```text
state.py
task.py
worker.py
```

问题：

当前 `run_worker()` 会计算：

```text
attempt + 1
```

但没有真正持久化到 state。

目标：

每次真实 Worker 执行都拥有唯一 attempt。

验收标准：

- 第一次运行 attempt=1。
- FIX 后 attempt=2。
- Retry 后继续递增。
- state.json 持久化当前 attempt。
- 日志使用 attempt-001 / attempt-002。
- evidence 正确归档。
- 重试不能覆盖旧日志。
- 重试不能覆盖旧 patch。
- PASS/FIX 引用真实 attempt。
- 测试覆盖至少三次连续 attempt。

完成状态：

```text
TODO
```

---

## P0-03
# dispatch: fix workspace isolation semantics for remote-worktree

负责人：

```text
W03
```

依赖：

```text
无
```

主要范围：

```text
dispatch.py
workspace selection logic
```

问题：

implement 默认 workspaceMode=worktree。

但 dispatcher 又只允许 local transport 使用 worktree。

这和 remote-worktree transport 自身发生冲突。

目标：

隔离方式由 transport 决定。

推荐规则：

```text
local + implement
→ local isolated worktree

remote-worktree + implement
→ remote isolated workspace

ssh + implement
→ existing exclusive

review/test
→ shared readonly（满足安全条件时）
```

验收标准：

- remote-worktree implement 不指定 workspaceMode 也能调度。
- remote-worktree 不再被 “worktree only supported for local” 拒绝。
- existing 同路径只能一个写任务。
- readonly 不允许和写任务冲突。
- 增加 transport × role dispatch matrix 测试。
- 删除重复 workspace 语义。

完成状态：

```text
TODO
```

---

## P0-04
# resources: enforce worker-to-host affinity during dispatch

负责人：

```text
W03
```

依赖：

```text
P0-03
```

主要范围：

```text
config.py
dispatch.py
worker resource validation
```

问题：

当前：

```text
ProjectConfig.sshHost
WorkerConfig.host
```

是两个独立配置。

dispatcher 没有严格保证 Worker 和实际执行 host 一致。

目标：

把 Worker 当成真实执行资源。

逻辑上：

```text
Worker ID
=
Host
+
CodeArts Account
+
CLI
+
Model
+
Concurrency
+
Capabilities
```

验收标准：

- W01 不能被错误绑定到 W03 host。
- 显式 worker/host 不匹配必须拒绝。
- 自动 worker selection 只能选 host-compatible worker。
- concurrency 针对真实执行资源计数。
- doctor 可发现 worker-host 配置冲突。
- 增加 affinity regression test。

完成状态：

```text
TODO
```

---

## P0-05
# runtime: add process supervisor and implement real task cancellation

负责人：

```text
W01
```

依赖：

```text
P0-01
```

建议新增：

```text
src/bridge/runtime/process_supervisor.py
```

职责：

```text
spawn
pid tracking
heartbeat
cancel
terminate
kill
exit collection
```

问题：

当前 cancel 基本只修改 state message。

不会真正取消 Worker。

目标：

真正实现 Worker 生命周期控制。

推荐状态：

```text
RUNNING
 ↓
CANCEL_REQUESTED
 ↓
terminate
 ↓
grace period
 ↓
kill if needed
 ↓
CANCELLED
```

验收标准：

- 增加 CANCELLED 状态。
- cancel 写正式取消请求。
- local Worker 能 terminate。
- grace period 后能 kill。
- SSH / remote Worker 有远端 execution identity。
- Cancel 后保留 workspace。
- Cancel 后保留 outbox。
- Cancel 后保留 evidence。
- Cancel 不得误判 FAILED/PASS。
- Cancel 幂等。
- daemon 重启后能处理遗留 cancel request。

完成状态：

```text
TODO
```

---

## P0-06
# runtime: implement soft-timeout checkpoint and assistance delivery

负责人：

```text
W01
```

依赖：

```text
P0-05
```

问题：

当前 soft_timeout_seconds 基本没有真实执行语义。

目标：

实现：

```text
RUNNING
   │
   ├── soft deadline
   │      ↓
   │ request checkpoint
   │      ↓
   │ CHECKPOINT.md
   │ ASSISTANCE_REQUEST.md
   │      ↓
   │ ASSISTANCE_REQUIRED
   │
   └── hard deadline
          ↓
       force kill
```

验收标准：

- soft timeout 和 hard timeout 独立。
- soft timeout 不直接 FAILED。
- Worker 能收到 checkpoint 请求。
- CHECKPOINT + ASSISTANCE_REQUEST → ASSISTANCE_REQUIRED。
- 已修改源码必须保留。
- hard timeout 才能 force kill。
- fake runner 可稳定测试 soft timeout。
- timeout 后不能永久留在无 PID RUNNING。

完成状态：

```text
TODO
```

---

## P0-07
# result: add canonical worker result classifier and state mapping

负责人：

```text
W02
```

依赖：

```text
P0-02
```

建议新增：

```text
src/bridge/result_classifier.py
```

输入：

```text
exit code
transport result
stdout
stderr
outbox files
checkpoint
blocker
auth error
quota error
timeout
cancel
```

输出：

```text
canonical state
```

必须至少支持：

```text
RESULT + TESTS + DIFF
→ REVIEW_REQUIRED

BLOCKER.md
→ BLOCKED

CHECKPOINT + ASSISTANCE_REQUEST
→ ASSISTANCE_REQUIRED

authorization error
→ AUTH_REQUIRED

temporary retry condition
→ RETRYABLE

cancel
→ CANCELLED

exit 0 but incomplete deliverables
→ FAILED

transport/protocol failure
→ FAILED
```

验收标准：

- 分类逻辑不散落到 transport。
- local / ssh / remote-worktree 使用同一 classifier。
- 定义清晰分类优先级。
- exit code 0 不能绕过 deliverable 检查。
- 每种 canonical state 至少一条测试。
- classifier 尽量纯函数。

完成状态：

```text
TODO
```

---

## P0-08
# ui-feedback: implement reliable runtime event echo, heartbeat and stale detection

负责人：

```text
W01 主实现
W04 独立验收
```

依赖：

```text
P0-05
P0-02
```

主要范围：

```text
process supervisor
worker runtime
state.py
progress.py
runtime event stream
```

问题：

当前 UI / progress 回显没有真正的实时事件链。

CodeArts 输出主要被 `capture_output=True` 缓存在子进程结束以后再一次性解析。

因此运行期间：

```text
Worker 正常执行
≠
UI 能持续看到事件
```

这会造成：

- 长时间没有任何回显。
- heartbeatSummary 经常为空。
- 用户无法判断任务是在运行、卡住还是 UI 自己没更新。
- Worker 已经完成，但 UI 可能直到下一次最终 state 更新才看到结果。
- UI 重启后没有可靠事件恢复机制。

目标：

建立：

```text
CodeArts / Worker
 ↓
incremental event reader
 ↓
sanitized event normalizer
 ↓
events.jsonl
 ↓
state heartbeat snapshot
 ↓
watch/progress UI
```

建议实现：

```text
src/bridge/runtime/events.py
```

或等价模块。

事件必须有单调递增 `seq`。

至少支持：

```text
status
heartbeat
tool
test
warning
terminal
```

禁止将模型原始私有 reasoning 直接送入 UI。

UI 只显示：

```text
任务状态
Worker
Attempt
Elapsed
Last Event Age
安全摘要
测试状态
Warning
Terminal Result
```

需要 stale detection：

```text
RUNNING + heartbeat fresh
→ LIVE

RUNNING + heartbeat 超过阈值
→ STALE

terminal state
→ DONE / FAILED / BLOCKED / ...
```

STALE 只是 UI/运行时可观测状态，不直接改变任务 canonical state。

验收标准：

- Worker 运行期间能持续产生 heartbeat。
- fake Worker 每 0.2~1 秒产生事件时，UI 在一个刷新周期内可见。
- `lastHeartbeat` 在运行期间持续更新。
- `lastEventAt` 随有效事件推进。
- `heartbeatSummary` 不再只在进程结束后更新。
- UI 晚启动时能显示当前 task snapshot。
- UI 重启后能从持久化事件恢复最近事件。
- UI 不依赖 daemon/Worker stdout 终端是否存在。
- 四个 Worker 并发时事件不会串 task。
- attempt 2 的事件不能混入 attempt 1。
- Worker 结束后 terminal 状态必须在一个刷新周期内显示。
- Worker 长时间无事件时 UI 显示 STALE。
- STALE 不自动改成 FAILED。
- 任何 UI event 写入前先进行敏感信息遮盖。
- UI event 不包含模型原始 chain-of-thought / private reasoning。
- event consumer 出错不得导致 Worker 退出。
- event file 写入失败必须留下明确 runtime warning。
- 增加“事件持续回显”“UI 重启恢复”“四 Worker 并发”“STALE 检测”自动测试。

完成状态：

```text
TODO
```

---

## P0-09
# qa: add end-to-end control-plane regression suite and CI

负责人：

```text
W04
```

依赖：

```text
跟随全部 P0 持续推进
```

W04 第一轮即可开始测试骨架，不需要等其他任务完成。

必须覆盖：

```text
create
→ dispatch
→ run
→ REVIEW_REQUIRED
```

```text
create
→ dispatch
→ FIX
→ attempt 2
```

```text
create
→ cancel
→ CANCELLED
```

```text
create
→ soft timeout
→ ASSISTANCE_REQUIRED
```

```text
remote-worktree implement
→ dispatch success
```

```text
wrong worker / host
→ dispatch rejected
```

```text
dependency unfinished
→ skipped
```

```text
dependency DONE
→ runnable
```

UI / 回显专项必须额外覆盖：

```text
running worker
→ heartbeat visible
```

```text
UI starts late
→ current snapshot visible
→ recent events recoverable
```

```text
UI restart
→ no blank state
→ event sequence resumes
```

```text
four workers emit concurrently
→ no cross-task event contamination
```

```text
worker becomes silent
→ UI shows STALE
→ canonical task state remains RUNNING
```

```text
worker terminates
→ terminal state visible within one refresh cycle
```

CI：

```text
push
pull_request
 ↓
pytest
```

验收标准：

- GitHub Actions 自动执行 test suite。
- PR 显示 pass/fail。
- E2E 使用 fake runner。
- 日常 CI 不依赖真实 CodeArts 额度。
- 外部 SSH 测试和普通 CI 分离。
- UI 回显测试不依赖人工观察终端。
- W04 对每个 P0 PR 做 acceptance review。

完成状态：

```text
TODO
```

---

## P0-10
# docs: establish one source of truth for version, protocol and runtime behavior

负责人：

```text
W04
```

依赖：

```text
P0-01
P0-02
P0-03
P0-04
P0-05
P0-06
P0-07
P0-08
P0-09
```

此任务必须最后做。

需要统一：

```text
README version
package version
daemon version
protocol version
license
CLI behavior
state machine
transport behavior
UI/event behavior
```

需要清理：

- README v0.1 与代码 2.0.0 冲突。
- PROFILE.md 中旧 PowerShell 描述。
- PROTOCOL.md 中旧 dispatcher 行为。
- README / pyproject / GitHub repository 的 License 描述不一致。
- 补充 UI/事件流、heartbeat、STALE 语义说明。

验收标准：

- 版本单一来源。
- 协议和 Python 实现一致。
- README Quick Start 可通过 E2E。
- License 声明统一。
- UI 回显行为有明确 contract。
- 建立以下文档：

```text
docs/
├── 00-PROJECT-BLUEPRINT.md
├── 01-ARCHITECTURE.md
└── 02-DEVELOPMENT-RULES.md
```

完成状态：

```text
TODO
```

---

# 7. P0 并行开发依赖图

```text
                    ┌──────── P0-01 Dispatch ────────┐
                    │              W01               │
                    │                                ▼
START ──────────────┼───────────────→ P0-05 Process Supervisor/Cancel
                    │                                │
                    │                                ▼
                    │                         P0-06 Soft Timeout
                    │                                │
                    │                                ▼
                    │                         P0-08 UI/Event Echo
                    │
                    ├──────── P0-02 Attempt ─────────┐
                    │              W02               │
                    │                                ▼
                    │                         P0-07 Result Classifier
                    │
                    └──────── P0-03 Workspace ───────┐
                                   W03               │
                                                     ▼
                                              P0-04 Host Affinity


               W04：P0-09 QA / E2E / CI
              ─────────────────────────▶
              跟随全部 P0 开发持续验收
              特别验收 UI 回显 / 重启恢复 / STALE / 四 Worker 并发


P0-01 ~ P0-09 全部 PASS
              │
              ▼
        P0-10 Docs Truth Reset
              │
              ▼
           P0 DONE
```

---

# 8. 第一轮立即执行计划

同时派发：

```text
W01 → P0-01
W02 → P0-02
W03 → P0-03
W04 → P0-09 第一阶段
```

注意：

W03 第一轮不要同时做 P0-04。

因为 P0-03 和 P0-04 都会修改 dispatch.py。

正确顺序：

```text
P0-03
 ↓
Review PASS
 ↓
P0-04
```

---

# 9. 第二轮执行计划

第一轮全部 Review 通过并合入新的集成基线后：

```text
W01 → P0-05
W02 → P0-07
W03 → P0-04
W04 → Review + 扩展 P0-09 E2E
```

W04 必须检查：

- 协议是否一致。
- 状态转换是否正确。
- 失败路径是否正确。
- 并发是否安全。
- 是否引入状态竞争。
- 是否有回归测试。

---

# 10. 第三轮与第四轮执行计划

第二轮合并后进入 Wave 3：

```text
W01 → P0-06 Soft Timeout
W02 → 帮助补 classifier/state regression
W03 → 修复 scheduler/resource edge cases
W04 → P0-09 持续 E2E acceptance
```

P0-05、P0-06 与 P0-02 稳定后进入 Wave 4：

```text
W01 → P0-08 UI/Event Echo
W02 → 协助检查 state/heartbeat snapshot 一致性
W03 → 检查并发 task/worker event 隔离
W04 → UI 回显专项验收
```

Wave 4 必须重点验证：

```text
持续回显
UI 晚启动
UI 重启
STALE
终态即时刷新
四 Worker 并发
attempt 隔离
敏感信息遮盖
```

最后：

```text
P0-10
```

完成文档 Truth Reset。

---

# 11. P0 完成标准

只有满足以下条件，才允许宣布 P0 DONE：

- CLI dispatch 和 daemon dispatch 行为一致。
- Worker 不会永久卡 QUEUED。
- attempt 正确递增。
- evidence / log 不覆盖。
- remote-worktree 默认可调度。
- Worker-host 强绑定。
- cancel 真正终止进程。
- soft timeout 真正产生 checkpoint。
- hard timeout 真正强制终止。
- Result Classifier 统一状态。
- Worker 运行过程中存在持续 heartbeat。
- UI 不再依赖 Worker 结束后才获得回显。
- UI 晚启动能看到当前 snapshot。
- UI 重启能恢复最近事件。
- UI 能明确显示 LIVE / STALE / terminal。
- 四 Worker 并发回显不串任务。
- attempt 间事件不串线。
- terminal 状态能在一个刷新周期内显示。
- UI 事件不包含私有 reasoning。
- UI 事件经过敏感信息遮盖。
- E2E 生命周期测试存在。
- UI 回显专项自动测试存在。
- GitHub Actions CI 存在。
- README / Protocol / Implementation 一致。
- W04 全量验收通过。

---

# 12. P1 — 高效率开发优化

P0 DONE 后才进入。

---

## P1-01
# health: production-grade doctor and worker readiness probes

负责人：

```text
W03
```

目标：

`bridge doctor` 不再只检查 binary 存不存在。

需要检测：

```text
SSH connectivity
CodeArts auth
CLI version
model availability
repo existence
repo clean state
workspace writable
Git
quota state
worker-host consistency
```

目标状态：

```text
READY
DEGRADED
AUTH_REQUIRED
QUOTA_EXHAUSTED
OFFLINE
```

调度器只给 READY Worker 派任务。

---

## P1-02
# scheduler: priority, estimated duration and critical-path scheduling

负责人：

```text
W03
```

Task META 增加：

```json
{
  "priority": 50,
  "estimatedMinutes": 8,
  "maxRetries": 1,
  "preferredWorkers": [],
  "resourceClass": "implementation"
}
```

Scheduler 综合考虑：

```text
dependsOn
critical path
priority
estimated duration
worker capability
worker availability
host
workspace conflict
quota
retry count
```

目标：

> Worker 能工作时，不应该因为调度器太简单而闲置。

---

## P1-03
# models: honor worker/project model configuration and role routing

负责人：

```text
W02
```

解决当前：

```text
worker.model
project.model
```

存在，但 transport 仍基本固定 REQUIRED_MODEL 的问题。

目标支持：

```text
Architect → strongest reasoning model
Implement → coding model
Review → reasoning model
Test → fast / lower-cost model
```

---

## P1-04
# policy: integrate minimal pre-check/post-check/approval gates

负责人：

```text
W01
```

只做最小接入：

```text
preChecks
 ↓
Worker
 ↓
postChecks
 ↓
approvalGate
```

暂时不要把 Bridge 做成大型 workflow engine。

---

## P1-05
# context: add project/module context packs and ADR system

负责人：

```text
W02
```

目标：

新 Worker 不再重新扫描整个项目。

建立：

```text
docs/
├── 00-PROJECT-BLUEPRINT.md
├── 01-ARCHITECTURE.md
├── 02-DEVELOPMENT-RULES.md
├── modules/
│   ├── dispatch.md
│   ├── runtime.md
│   ├── worker.md
│   ├── transport.md
│   └── policy.md
└── decisions/
    ├── ADR-001-worker-isolation.md
    ├── ADR-002-task-state-machine.md
    └── ADR-003-ai-responsibilities.md
```

派发时只给 Worker：

```text
TASK
+
相关 module docs
+
相关 ADR
+
相关 contract
+
baseline SHA
```

不要重新理解整个仓库。

---

## P1-06
# telemetry: track throughput, first-pass rate, timeout and worker utilization

负责人：

```text
W03
```

至少统计：

```text
taskQueueTime
executionTime
reviewTime
firstPassRate
fixRate
retryRate
timeoutRate
workerUtilization
tokensPerTask
integrationConflictRate
tasksPerHour
requirementToValidatedPatchTime
```

核心指标：

> Requirement → Validated Patch 需要多长时间。

---

# 13. P1 推荐依赖

```text
P0 DONE
   │
   ├── P1-01 Worker Health ───┐
   │                          ▼
   │                    P1-02 Scheduler
   │                          │
   │                          ▼
   │                    P1-06 Telemetry
   │
   ├── P1-03 Model Routing
   │
   ├── P1-04 Policy Integration
   │
   └── P1-05 Context Pack
```

P1-03 / P1-04 / P1-05 可以并行。

P1-02 最好建立在 P1-01 Worker Health 上。

---

# 14. Architect AI 每轮持续推进规则

Architect 每次开始新的开发轮次必须执行：

## Step 1：读取当前基线

确认：

```text
main HEAD
open tasks
active tasks
completed tasks
failed tasks
worker health
```

---

## Step 2：读取本文件

确认：

```text
当前 Phase
当前 Wave
每个 Worker 当前负责人
依赖是否已经满足
```

---

## Step 3：检查上一轮交付

只优先读取：

```text
RESULT.md
DIFF.stat
TESTS.md
DIFF.patch
```

必要时查看目标 diff。

不要默认读取：

```text
完整 stdout
完整 stderr
完整 reasoning
整个仓库
```

---

## Step 4：Review

只能给出：

```text
PASS
FIX
ARCHITECTURAL_BLOCKER
```

FIX 必须是当前交付物的窄整改。

若新增模块或新增验收阶段：

```text
建立新的 Task
```

不要不断往原任务追加范围。

---

## Step 5：合入并更新基线

Worker Patch 通过 Review 后：

```text
integrate
 ↓
run focused regression
 ↓
update main baseline
```

后继写任务必须使用新基线。

---

## Step 6：立即补充 Worker 队列

某 Worker 完成后，不应长期空闲。

如果存在安全的后继实现任务：

```text
立即派发
```

如果没有安全的写任务：

```text
安排 review
test
contract inspection
regression design
```

不要为了提高并发而违反依赖关系。

---

## Step 7：更新本文件

每轮结束至少更新：

```text
Issue 状态
当前 baseline
已完成 Wave
失败原因
新发现问题
下一轮分配
```

本文件是持续开发的工程状态文档，不是一次性报告。

---

# 15. 状态标记规范

本文件中每个任务使用：

```text
TODO
READY
IN_PROGRESS
REVIEW
FIX_REQUIRED
BLOCKED
DONE
```

不要使用模糊状态。

---

# 16. Task 创建模板

Architect 创建任务时使用：

```markdown
# TASK

## Objective

## Current Situation

## Required Changes

1.
2.
3.

## Constraints

## Implementation Direction

## Acceptance Criteria

- [ ]
- [ ]
- [ ]

## Relevant Files

## Relevant Docs

## Dependencies

## Baseline

## Deliverables

- RESULT.md
- DIFF.stat
- TESTS.md
- DIFF.patch
```

---

# 17. Review 模板

## PASS

```markdown
# PASS

Task:
Baseline:
Reviewed Commit:

Acceptance:
- PASS

Regression:
- PASS

Integration:
- Approved
```

---

## FIX

```markdown
# FIX

Task:

Issues:

1.
2.

Required Fixes:

1.
2.

Acceptance:

- [ ]
- [ ]
```

只写增量问题。

---

## ARCHITECTURAL_BLOCKER

```markdown
# ARCHITECTURAL BLOCKER

Task:

Problem:

Affected Boundary:

Options:

Decision Needed:

Impact:
```

---

# 18. 高效率开发核心原则

始终遵守以下规则。

## 原则 1

不要让所有 AI 都重新理解整个项目。

---

## 原则 2

不要让 Architect 长时间写普通实现代码。

---

## 原则 3

不要让 Worker 自己决定跨模块架构。

---

## 原则 4

不要让两个实现 Worker 同时修改共享核心文件。

---

## 原则 5

尽量让 W01 / W02 / W03 同时工作在不同边界。

---

## 原则 6

让 W04 独立验证，而不是参与普通编码。

---

## 原则 7

Focused test 通过后优先保护交付物，再跑全量测试。

---

## 原则 8

达到 soft timeout 时交 checkpoint，不继续硬耗上下文。

---

## 原则 9

Bridge 本身保持简单。

不要为未来假想需求提前加入：

```text
大型数据库
复杂权限平台
复杂 UI
复杂 workflow DSL
```

---

## 原则 10

每次新增功能都要问：

> 它是否直接提高 Requirement → Validated Patch 的速度、稳定性或并行能力？

如果答案是否定的，应降低优先级。

---

# 19. 当前立即执行指令

当前 Phase：

```text
P0
```

当前 Wave：

```text
Wave 1
```

立即派发：

```text
W01
→ P0-01
control-plane: unify CLI and daemon dispatch execution semantics

W02
→ P0-02
state: persist attempt lifecycle and prevent evidence/log overwrite

W03
→ P0-03
dispatch: fix workspace isolation semantics for remote-worktree

W04
→ P0-09 Stage 1
qa: build E2E / CI scaffold，并提前建立 UI 回显专项测试骨架
```

当前禁止提前执行：

```text
P0-04
P0-05
P0-06
P0-07
P0-08
P0-10
P1-*
```

除非其依赖已经满足，并且 Architect 更新本文件状态。

---

# 20. 下一轮触发条件

当以下全部满足：

```text
P0-01 = DONE
P0-02 = DONE
P0-03 = DONE
P0-09 Stage 1 = DONE
```

进入 Wave 2：

```text
W01 → P0-05
W02 → P0-07
W03 → P0-04
W04 → E2E Review / Regression
```

---

# 21. P0 结束后目标开发形态

最终目标：

```text
                   User
                    │
                    ▼
             ┌──────────────┐
             │ Architect AI │
             └──────┬───────┘
                    │
                Task DAG
                    │
                    ▼
       ┌────────────────────────┐
       │    CodeartsBridge      │
       │                        │
       │ Task Store             │
       │ Scheduler              │
       │ Worker Registry        │
       │ Resource Manager       │
       │ Lock / Lease           │
       │ Process Supervisor     │
       │ Timeout / Retry        │
       │ Result Classifier      │
       │ Git Integration Queue  │
       └──────┬─────┬─────┬────┘
              │     │     │
          ┌───▼─┐ ┌─▼───┐ ┌▼────┐
          │ W01 │ │ W02 │ │ W03 │
          │ DEV │ │ DEV │ │ DEV │
          └──┬──┘ └──┬──┘ └──┬──┘
             │        │       │
             └────────┼───────┘
                      ▼
                   ┌─────┐
                   │ W04 │
                   │ QA  │
                   └──┬──┘
                      │
                      ▼
              Architect Review
                      │
                      ▼
                 Integration
                      │
                      ▼
                    Main
```

---

# 22. 最终目标

CodeartsBridge 的目标不是拥有最多功能。

目标是：

> **用最少的控制面复杂度，让多个 AI 工程师持续、可靠、低冲突、高利用率地输出可验证代码。**

最终衡量标准：

```text
Requirement
 ↓
Task Planning
 ↓
Parallel Development
 ↓
Independent QA
 ↓
Validated Patch
```

整个链路应越来越短、越来越自动、越来越稳定。

---

# 23. 当前状态记录

```text
Phase: P1
Wave: P1-03 进行中
Baseline:
c190fc8 feat(P1-02): priority, estimated duration and critical-path scheduling

P0-01: DONE  # 0cf338c 统一 CLI/daemon dispatch
P0-02: DONE  # 0cf338c attempt 持久化
P0-03: DONE  # 0cf338c transport 感知 workspace 隔离
P0-04: DONE  # 27bc573 host affinity
P0-05: DONE  # 27bc573 process supervisor + CANCELLED
P0-06: DONE  # 10ae6e0 soft timeout + ASSISTANCE_REQUIRED
P0-07: DONE  # 27bc573 result classifier
P0-08: DONE  # 05c1f93 events/heartbeat/stale
P0-09: DONE  # 531eb5e E2E/CI + docs truth reset
P0-10: DONE  # 531eb5e docs truth reset

P1-01: DONE  # 53fde7d doctor 探针
P1-02: DONE  # c190fc8 优先级调度
P1-03: IN_PROGRESS  # 模型路由
P1-04: TODO  # 策略门控（接入旧版链 worker.py）
P1-05: TODO  # 上下文包（纯文档路径 A）
P1-06: TODO  # 遥测统计
```

---


## 23.1 UI 回显检查强制项

任何涉及以下模块的 Review：

```text
progress.py
state.py
worker.py
daemon.py
process supervisor
transport streaming
runtime events
```

都必须额外回答：

```text
1. 运行中有没有持续事件？
2. UI 晚打开是否能恢复当前状态？
3. UI 重启是否会空白？
4. heartbeat 是否真的有生产者？
5. lastEventAt 是否持续推进？
6. Worker 已结束时 UI 是否立即得到 terminal？
7. Worker 静默时能否显示 STALE？
8. 四个 Worker 是否会串回显？
9. attempt 是否会串事件？
10. 是否泄露敏感信息或私有 reasoning？
```

只要其中任一项无法确认，就不能把 UI 回显相关任务判为 PASS。

---

# 24. 对后续 AI 的直接指令

如果你是接手本项目的 Architect AI：

1. 不要重新设计整个项目。
2. 不要跳过 P0 直接开发 P1。
3. 先读取 main 最新状态。
4. 对照本文件确认当前 Wave。
5. 检查上一轮 Worker 结果。
6. PASS 后合入。
7. 更新 baseline。
8. 按依赖关系创建下一批 Task。
9. 保持 W01/W02/W03 尽量并行但不修改同一核心边界。
10. W04 始终负责独立 QA。
11. 新发现问题先判断是否阻塞当前 P0。
12. 非阻塞问题加入后续 backlog，不得随手扩大当前 Task。
13. 每轮结束更新本文件。
14. 持续推进，直到当前 Phase 的全部验收条件满足。

