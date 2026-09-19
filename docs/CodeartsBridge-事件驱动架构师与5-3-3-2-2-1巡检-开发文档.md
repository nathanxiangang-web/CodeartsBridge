# CodeartsBridge 事件驱动架构师调度与 5/3/3/2/2/1 分频巡检开发文档

> 文档类型：可直接进入开发阶段的实施设计  
> 适用仓库：`nathanxiangang-web/CodeartsBridge`  
> 日期：2026-09-19  
> 目标版本：Architect Reactor / Supervisor v1  
> 核心目标：**消灭“架构师干等 + 单 Worker 干活 + 其他 Worker 空闲”的低利用率模式，把 Architect 从主动轮询者改造成被事件唤醒的决策者。**  
> 本文档重点覆盖：架构、时间模型、事件模型、状态迁移、模块拆分、详细代码落点、迁移顺序、测试、故障恢复、兼容、性能、填坑清单、回滚、验收标准。

---

# 0. 一句话结论

本轮改造不应该继续让 Architect 每隔几秒扫描全部任务。

应改为：

```text
Worker 正常执行
    ↓
Supervisor 维护“每任务独立时钟”
    ↓
5 / 8 / 11 / 13 / 15 / 16 分钟触发程序级巡检
    ↓
正常：Supervisor 自己消化，不调用 Architect
异常：发事件唤醒 Architect
完成：Worker 状态变为 REVIEW_REQUIRED，立刻发 review.required
    ↓
Architect Reactor 被事件唤醒
    ↓
review / FIX / integration / re-plan
```

因此：

> **5/3/3/2/2/1 是 Supervisor 的巡检节奏，不是 Architect 的模型调用节奏。**

Architect 只处理：

```text
review.required
assistance.required
runtime.timeout
supervision.alert
conflict.required
capacity.available
dependency.unlocked
```

不再主动扫全部 Worker。

---

# 1. 当前仓库现状与问题

## 1.1 当前 Pipeline 是 polling-first

当前：

```text
src/bridge/pipeline.py
```

默认：

```python
interval = 10.0
```

循环中：

```text
run_pipeline_cycle()
    ↓
architect_loop()
    ↓
auto_dispatch()
    ↓
integrate_loop()
    ↓
conflict check
```

活跃任务期间循环 sleep 约 `interval / 2`，默认约 5 秒一次。

这意味着 Architect Review 的触发方式实际是：

```text
每隔几秒
    ↓
扫描 tasks/
    ↓
找 REVIEW_REQUIRED
    ↓
review
```

这属于 polling，而不是 event driven。

## 1.2 当前 architect_loop 会扫描所有任务目录

当前：

```text
src/bridge/architect_loop.py
```

核心逻辑：

```python
_scan_review_required_tasks(tasks_root)
```

然后：

```text
for task_dir in tasks/*
    read state
    if REVIEW_REQUIRED:
        review
```

问题：

1. 没任务时也扫描。
2. Worker 正常运行时也扫描。
3. Worker 刚完成时最多还要等下一轮。
4. Architect 生命周期和 pipeline tick 绑定。
5. 无法精确知道哪个 Worker 在第几分钟。
6. 无法利用“距离下个需要处理事件还有多久”来塞背景小任务。

## 1.3 当前已经有 Event 基础，但未接成控制链

已有：

```text
src/bridge/core/events.py
```

已经定义：

```text
TASK_CREATED
TASK_STATE_CHANGED
ASSIGNMENT_CREATED
ASSIGNMENT_STARTED
ASSIGNMENT_FINISHED
RUNTIME_HEARTBEAT
RUNTIME_TIMEOUT
RUNTIME_CANCELLED
REVIEW_REQUIRED
REVIEW_COMPLETED
INTEGRATION_STARTED
INTEGRATION_COMPLETED
POLICY_FAILED
```

并已有：

```python
EventStore
```

同时：

```text
src/bridge/api/server.py
GET /api/events
```

已经能通过 SSE 输出 EventStore。

真正缺的是：

```text
状态变化
    ↓
写 EventStore
    ↓
内部 Reactor 消费
```

## 1.4 当前还有两套 state 实现

当前至少存在：

```text
src/bridge/state.py
src/bridge/core/state.py
```

两边都有：

```python
set_state()
```

这是本次最大的填坑风险之一。

如果只改其中一个：

```text
某些任务有事件
某些任务没事件
```

最后会变成非常难排查的偶发不触发。

因此本轮必须先定义：

> **统一状态事件出口。**

---

# 2. 设计目标

本轮同时解决 6 个问题。

## 2.1 Worker 每人独立计时

计时基准必须是：

```text
worker task RUNNING 时间
```

不是：

```text
Pipeline 启动时间
Architect 循环时间
任务创建时间
任务 QUEUED 时间
```

例如：

```text
W01 15:00 RUNNING
W02 15:02 RUNNING
```

则：

```text
W01 15:05 第一次巡检
W02 15:07 第一次巡检
```

互不影响。

## 2.2 0~5 分钟完全不打扰

Worker 开始后前 5 分钟：

```text
不查收
不催
不触发 Architect
不进行无意义状态扫描
```

只保留：

```text
runtime heartbeat
event logging
process liveness
```

## 2.3 5/3/3/2/2/1

用户定义节奏：

```text
5 / 3 / 3 / 2 / 2 / 1
```

转换成相对 RUNNING 的绝对偏移：

```text
T+05
T+08
T+11
T+13
T+15
T+16
```

用途：

```text
T+05 轻巡检
T+08 轻巡检
T+11 中巡检
T+13 交付风险巡检
T+15 硬查收
T+16 收尾收敛
```

## 2.4 完成立即触发，不等巡检点

如果 Worker T+06 就完成：

```text
RUNNING -> REVIEW_REQUIRED
```

必须立即：

```text
publish review.required
```

然后 Architect 立即查收。

同时取消该任务剩余：

```text
T+08
T+11
T+13
T+15
T+16
```

## 2.5 Architect 空闲时可以干小活

Architect 空闲期间允许执行：

```text
下一 Wave 拆分
Acceptance Criteria 细化
依赖任务预建
ADR / 文档整理
失败原因聚类
提前准备 FIX 模板
容量补任务
```

但必须：

```text
可抢占
短时
无长锁
不阻塞 review.required
```

建议：

```text
background task max = 90s
deadline reserve = 30s
```

## 2.6 15 分钟硬查收不依赖 Architect 主动动作

T+15 由 Supervisor / Runtime 自动：

```text
停止执行
拉 outbox
保存 diff
salvage
分类结果
发事件
```

Architect 只消费结果。

---

# 3. 核心架构

```text
                           ┌─────────────────────┐
                           │    Architect AI     │
                           │    Event Reactor    │
                           └──────────▲──────────┘
                                      │
                                actionable only
                                      │
                           ┌──────────┴──────────┐
                           │  Architect Queue    │
                           │ Priority + Dedupe   │
                           └──────────▲──────────┘
                                      │
        ┌─────────────────────────────┼─────────────────────────────┐
        │                             │                             │
 review.required              supervision.alert             capacity.available
 assistance.required          runtime.timeout               dependency.unlocked
        ▲                             ▲                             ▲
        │                             │                             │
        │                   ┌─────────┴─────────┐                   │
        │                   │    Supervisor     │                   │
        │                   │ DeadlineScheduler │                   │
        │                   │ Inspector         │                   │
        │                   └─────────▲─────────┘                   │
        │                             │                             │
        │                  per-task independent timer               │
        │                             │                             │
        │                    5/8/11/13/15/16                        │
        │                             │                             │
        └─────────────────────────────┼─────────────────────────────┘
                                      │
                               Worker / Runtime
```

---

# 4. 新模块目录

建议新增：

```text
src/bridge/supervision/
├── __init__.py
├── model.py
├── schedule.py
├── inspector.py
├── supervisor.py
├── reactor.py
├── queue.py
├── recovery.py
└── policy.py
```

配套新增：

```text
tests/supervision/
├── test_schedule.py
├── test_inspector.py
├── test_reactor.py
├── test_queue.py
├── test_recovery.py
├── test_state_events.py
├── test_supervision_e2e.py
└── test_architect_background.py
```

---

# 5. 数据模型

## 5.1 SupervisionPlan

新增：

```python
@dataclass
class SupervisionPlan:
    task_id: str
    worker_id: str | None
    running_at: str

    next_stage: int
    next_due_at: str | None

    completed_stages: list[int]
    cancelled: bool = False

    last_event_id: str | None = None
    last_event_at: str | None = None
    last_progress_hash: str | None = None

    no_progress_count: int = 0
    repeated_error_count: int = 0

    version: int = 1
```

持久化：

```text
runtime/supervision/tasks/<task-id>.json
```

不要只存在内存。

## 5.2 DeadlineEntry

```python
@dataclass(order=True)
class DeadlineEntry:
    due_monotonic: float
    due_wallclock: str
    task_id: str
    stage: int
    generation: int
```

使用：

```python
heapq
```

排序。

## 5.3 ArchitectEvent

```python
@dataclass
class ArchitectEvent:
    event_id: str
    type: str
    task_id: str | None
    worker_id: str | None

    priority: int
    created_at: str

    payload: dict
    dedupe_key: str

    attempt: int = 0
```

---

# 6. 巡检时间模型

## 6.1 保存绝对 offset，不保存增量

配置：

```python
SUPERVISION_OFFSETS_SECONDS = (
    300,
    480,
    660,
    780,
    900,
    960,
)
```

禁止内部按：

```python
[5, 3, 3, 2, 2, 1]
```

逐段累加。

原因是巡检执行本身会耗时，累加会漂移。

例如：

```text
T+5 巡检实际执行耗时 30 秒
```

如果下一次直接 `+3m`：

```text
会变成 T+8:30
```

最终硬查收可能漂到 15 分钟之后。

## 6.2 时间基准

同时保存：

```text
wall clock
monotonic clock
```

Wall clock 用于：

```text
持久化 / UI / restart
```

Monotonic 用于：

```text
当前进程精确计时
```

避免 NTP 或系统时间回拨。

## 6.3 重启恢复

Supervisor 重启后：

```text
读取 runningAt
读取 completedStages
当前时间 - runningAt
```

例如：

```text
runningAt = 15:00
Supervisor 15:09 重启
```

恢复：

```text
5m 已过
8m 已过
11m 未到
```

正确动作：

```text
补一次 recovery inspection
标记 Stage 1/2 已经过期
nextDue = T+11
```

不能重新从第 5 分钟开始。

---

# 7. 六级巡检定义

## Stage 1 — T+5：轻巡检

目标：只判断 Worker 是否活着、是否有进展。

读取：

```text
state
lastHeartbeat
lastEventAt
session event count
tool count
reasoning count
git status hash（可选）
outbox file count
```

正常条件任一满足：

```text
heartbeat 新鲜
lastEventAt 前进
eventCount 增长
toolCount 增长
git diff 变化
outbox 变化
```

结果：

```text
HEALTHY
```

行为：

```text
记录
不通知 Architect
schedule T+8
```

## Stage 2 — T+8：轻巡检加强

增加检测：

```text
相同错误文本重复
相同 tool call 重复
parser failure 重复
permission failure 重复
连续无 diff
连续无 outbox
```

如果：

```text
no_progress_count < 2
```

继续。

如果：

```text
no_progress_count >= 2
```

发：

```text
supervision.alert
```

Architect 才介入。

## Stage 3 — T+11：中巡检

检查：

```text
是否已有变更
是否已有测试运行
是否有 checkpoint
是否已经开始写 RESULT
是否重复失败
是否还停留在纯分析
```

分类：

```text
ON_TRACK
AT_RISK
STALLED
```

ON_TRACK：继续 T+13。

AT_RISK：发低优先级 supervision.alert。

STALLED：发高优先级 supervision.alert。

## Stage 4 — T+13：交付风险巡检

执行：

```text
snapshot git diff
snapshot outbox
检查 CHECKPOINT
检查 TESTS
检查 RESULT
```

如果 Worker Runtime 支持：

```text
emit SOFT_DELIVERY_REQUEST
```

否则只准备 salvage。

## Stage 5 — T+15：硬查收

必须由 Runtime/Supervisor 负责。

步骤：

```text
1. 停止 Worker 继续编码
2. 请求 graceful stop
3. 5 秒后仍活着则 kill
4. 拉 outbox
5. 保存 git status
6. 保存 git diff
7. 保存 DIFF.stat
8. 保存最后事件
9. 分类结果
```

结果分类：

### A. 已完整交付

有：

```text
RESULT.md
TESTS.md
DIFF.stat
```

则：

```text
REVIEW_REQUIRED
```

触发：

```text
review.required
```

### B. 有有效工作但不完整

有：

```text
git diff
CHECKPOINT
partial output
```

则：

```text
ASSISTANCE_REQUIRED
```

触发：

```text
assistance.required
```

### C. 完全无产出

则：

```text
FAILED / TIMED_OUT
```

触发：

```text
runtime.timeout
```

## Stage 6 — T+16：状态收敛

只负责清理。

检查：

```text
process 是否仍活着
lease 是否释放
assignment 是否 finished
task 是否还 RUNNING
workspace 是否保留
outbox 是否已同步
```

如果发现：

```text
RUNNING + 无进程
```

则强制收敛：

```text
有 deliverables -> REVIEW_REQUIRED
有 diff -> ASSISTANCE_REQUIRED
无产出 -> FAILED
```

Stage 6 不允许 Worker 再继续写代码。

---

# 8. Inspector 设计

## 8.1 Inspector 不调用 AI

`inspector.py` 必须纯程序。

```python
@dataclass
class InspectionResult:
    health: str
    progress: str
    severity: str
    reason: str

    event_delta: int
    tool_delta: int
    heartbeat_age_seconds: float | None

    repeated_errors: list[str]
    has_diff: bool
    has_outbox: bool
```

## 8.2 Progress Fingerprint

每次巡检生成：

```text
progress_hash
```

可由：

```text
lastEventAt
eventCount
toolCount
outbox metadata
git diff stat
state
```

组合后 sha1。

如果 hash 不变：

```text
no_progress_count += 1
```

变化：

```text
no_progress_count = 0
```

## 8.3 错误重复检测

从最近事件或 stderr 中提取：

```text
failed to parse target path
permission denied
auto-rejecting
write rejected
connection refused
authentication failed
timeout
```

Normalize：

```text
去时间戳
去 ANSI
去随机临时路径
截断参数
```

同类错误达到阈值：

```text
STALLED
```

---

# 9. Event Bus 改造

## 9.1 EventStore 当前存在性能坑

当前 `EventStore.append()` 是：

```text
读完整 events.jsonl
+ append line
+ atomic_write 整个文件
```

随着事件增加是 O(n)。

必须改成真正 append：

```python
with path.open("a", encoding="utf-8") as f:
    f.write(line)
    f.flush()
```

需要更强落盘时再 fsync。

## 9.2 SSE 当前存在 recent(100) 游标坑

当前 API 用：

```text
recent(100)
len(recent) > last_count
```

事件达到 100 条后，新事件进入时长度仍为 100，这种判断会失效。

必须新增：

```text
seq
```

Event：

```json
{
  "seq": 12345
}
```

EventStore 增加：

```python
recent_after(seq)
```

## 9.3 内部 Reactor 不依赖 SSE

浏览器 SSE 和内部 Architect Reactor 必须解耦。

内部 Reactor 直接读：

```text
EventStore / internal queue
```

不要通过 HTTP `/api/events` 自己订阅自己。

---

# 10. 统一状态事件出口

新增：

```text
src/bridge/state_events.py
```

提供：

```python
def emit_state_changed(
    bridge_root: Path,
    task_dir: Path,
    old_state: str,
    new_state: str,
    state: dict,
) -> None:
    ...
```

`src/bridge/state.py` 和 `src/bridge/core/state.py` 两边都必须调用。

建议 state 增加：

```json
{
  "revision": 17
}
```

每次真正状态迁移：

```text
revision + 1
```

Event：

```json
{
  "type": "task.state_changed",
  "payload": {
    "from": "RUNNING",
    "to": "REVIEW_REQUIRED",
    "revision": 17
  }
}
```

---

# 11. 状态事件映射

```text
RUNNING
    -> supervision.started

RUNNING -> REVIEW_REQUIRED
    -> review.required

RUNNING -> ASSISTANCE_REQUIRED
    -> assistance.required

RUNNING -> AUTH_REQUIRED
    -> auth.required

RUNNING -> FAILED
    -> task.failed

REVIEW_REQUIRED -> APPROVED
    -> review.completed

FIX_REQUIRED / READY
    -> task.dispatchable

DONE
    -> task.done

CONFLICT
    -> conflict.required
```

---

# 12. DeadlineScheduler

核心伪代码：

```python
class DeadlineScheduler:
    def __init__(self):
        self.heap = []
        self.generation = {}

    def start_task(self, task_id, running_at):
        gen = self.generation.get(task_id, 0) + 1
        self.generation[task_id] = gen

        for stage, offset in enumerate(OFFSETS, start=1):
            push(
                due=running_at + offset,
                task_id=task_id,
                stage=stage,
                generation=gen,
            )

    def cancel_task(self, task_id):
        self.generation[task_id] += 1

    def pop_due(self, now):
        while heap and heap[0].due <= now:
            entry = heappop(heap)
            if entry.generation != self.generation[entry.task_id]:
                continue
            yield entry
```

重点：取消任务不要 O(n) 从 heap 删除，直接 generation++。

---

# 13. Architect Queue

## 13.1 优先级

```text
P0 review.required
P0 runtime.timeout
P0 assistance.required
P0 conflict.required

P1 supervision.alert
P1 auth.required

P2 capacity.available
P2 dependency.unlocked

P3 background planning
P3 docs/ADR
```

## 13.2 去重

例如：

```text
T+8 STALLED
T+11 STALLED
T+13 STALLED
```

不能生成三个相同 Architect 任务。

使用：

```text
dedupe_key = supervision.alert:<task-id>:attempt-N
```

已有同 key 时：

```text
升级 severity
更新时间
不要重复入队
```

## 13.3 At-least-once

必须假设同一个事件可能收到两次。

Reactor 在处理 review 前先检查：

```text
current state == REVIEW_REQUIRED
```

否则忽略。

---

# 14. Architect Reactor

新增：

```text
src/bridge/supervision/reactor.py
```

职责：

```text
消费 ArchitectQueue
按优先级执行
```

收到：

```text
review.required
```

调用：

```python
review_task(task_id)
```

收到：

```text
assistance.required
```

判断：

```text
能否拆更小任务
是否重派
是否需要 FIX
是否需要用户
```

收到：

```text
supervision.alert
```

只给 Architect 精简上下文：

```text
task
worker
elapsed
last progress
repeated errors
diff state
outbox state
```

不要把整个 session log 塞进去。

---

# 15. Architect 背景小任务

Supervisor 始终知道：

```text
next_due_at
```

Architect 空闲时：

```python
slack = next_due_at - now
```

规则：

```text
slack <= 120s
    不启动背景任务

slack > 120s
    允许 max 90s 背景任务
```

参数：

```text
BACKGROUND_MAX_SECONDS = 90
DEADLINE_RESERVE_SECONDS = 30
```

适合任务：

```text
下一 Wave 拆分
Acceptance Criteria
后续 dependsOn 任务预建
ADR
失败统计
FIX 草案
```

不适合：

```text
10 分钟大分析
不可中断长任务
全仓重构
```

---

# 16. capacity.available

检测条件：

```text
enabled workers = 4
running workers <= 1
ready tasks = 0
项目仍有已知后续工作
```

发：

```text
capacity.available
```

Architect 提前创建：

```text
UI-01 READY dependsOn=[UI-00]
UI-02 READY dependsOn=[UI-00]
UI-03 READY dependsOn=[UI-00]
UI-04 READY dependsOn=[UI-00]
```

UI-00 一完成后，依赖解锁即可并行派发。

注意：capacity.available 不能让 Architect 凭空扩大 scope，只能基于已知 roadmap / 用户批准范围。

---

# 17. Pipeline 改造

## Phase 1：兼容模式

保留 pipeline loop，但 Architect Review 改为事件优先。

旧 polling 作为 fallback。

## Phase 2：事件模式

最终 pipeline 只负责启动：

```text
Supervisor
ArchitectReactor
DispatcherReactor
IntegrationReactor
Reconciler
```

不再每 5 秒整套扫描一遍。

---

# 18. 详细文件修改清单

## 新增

```text
src/bridge/state_events.py

src/bridge/supervision/__init__.py
src/bridge/supervision/model.py
src/bridge/supervision/schedule.py
src/bridge/supervision/inspector.py
src/bridge/supervision/supervisor.py
src/bridge/supervision/queue.py
src/bridge/supervision/reactor.py
src/bridge/supervision/recovery.py
src/bridge/supervision/policy.py
```

## 修改

```text
src/bridge/state.py
src/bridge/core/state.py
src/bridge/core/events.py
src/bridge/api/server.py
src/bridge/architect_loop.py
src/bridge/pipeline.py
src/bridge/auto_dispatch.py
src/bridge/daemon.py
src/bridge/worker.py
```

---

# 19. 配置

新增：

```text
supervision.json
```

示例：

```json
{
  "schemaVersion": 1,
  "enabled": true,
  "offsetsSeconds": [300, 480, 660, 780, 900, 960],

  "heartbeatStaleSeconds": 90,
  "noProgressThreshold": 2,
  "repeatedErrorThreshold": 3,

  "background": {
    "enabled": true,
    "maxSeconds": 90,
    "reserveBeforeDeadlineSeconds": 30,
    "minimumSlackSeconds": 120
  },

  "hardCollect": {
    "graceSeconds": 5,
    "salvage": true
  }
}
```

---

# 20. 状态兼容

不要新增 canonical state：

```text
CHECKING
INSPECTING
```

巡检不是业务状态。

巡检状态只存：

```text
runtime/supervision/tasks/*.json
```

任务仍使用：

```text
RUNNING
REVIEW_REQUIRED
ASSISTANCE_REQUIRED
FAILED
...
```

否则会破坏现有 scheduler / UI / telemetry。

---

# 21. 填坑清单

## 坑 1：两套 set_state

位置：

```text
src/bridge/state.py
src/bridge/core/state.py
```

解决：

```text
统一 state_events.py
两套都调用同一 emit
```

## 坑 2：runningAt 时间戳不一致

Supervisor 必须依赖可靠 runningAt。

新任务要求 RUNNING 首次进入时原子写 `runningAt`，且 write-once。

旧任务 fallback：

```text
runningAt
startedAt
assignment.createdAt
state.updatedAt
```

## 坑 3：Retry/FIX 后旧 timer 误触发

同一个 task 可能多 attempt。

Timer key 必须至少包含：

```text
taskId + generation
```

更好：

```text
taskId + attempt
```

每次新 attempt generation++。

## 坑 4：重启 timer 丢失

Supervisor plan 必须落盘：

```text
runtime/supervision/tasks/<task>.json
```

## 坑 5：系统时间调整

运行期用 monotonic，持久化用 UTC wall clock。

## 坑 6：EventStore append O(n)

必须改 append-only。

## 坑 7：SSE recent(100) 卡住

必须上 seq cursor。

## 坑 8：EventStore 多进程并发写

MVP 用 file lock；长期考虑单 EventWriter。

## 坑 9：重复 Review

新 Reactor 与旧 polling 过渡期可能同时 review。

必须：

```text
state check
review lock
```

否则可能创建重复 FIX task。

## 坑 10：旧 architect_loop scan 没关闭

上线 Reactor 后必须有开关：

```text
architectPollingReview
```

最终默认 false。

## 坑 11：Supervisor T+15 与 Transport hard timeout 双杀

必须定义唯一 kill owner。

短期：

```text
Transport/Runtime = kill owner
Supervisor = hard collect + reconcile owner
```

长期 Worker Runtime 统一处理。

## 坑 12：T+15 不能变成“再等等”

硬线就是硬线。

继续工作必须创建：

```text
new attempt
或 follow-up task
```

不能延长旧任务。

## 坑 13：T+16 不再写代码

只 cleanup。

## 坑 14：Heartbeat 不等于 Progress

AI 可以一直 heartbeat 但原地打转。

必须有 progress fingerprint。

## 坑 15：Event 数增长不等于 Progress

重复同一个 parser error 也会增长。

必须做 normalized error signature。

## 坑 16：Git diff 不适用于所有 role

implement 强信号；review/test 仅弱信号或不用。

## 坑 17：共享工作区 diff 污染

shared workspace 不能把 diff 当强信号。

## 坑 18：outbox mtime 不可靠

比较：

```text
filename + size + optional hash
```

## 坑 19：背景 Architect 抢占

第一版背景任务必须短，最多 60~90 秒。

后续再做可抢占 Popen。

## 坑 20：capacity.available 事件风暴

同项目加 cooldown：

```text
60 秒内最多一个
```

## 坑 21：capacity.available 不能扩大 scope

只能拆已有 roadmap 范围。

## 坑 22：预建 READY 任务不能绕过 dependsOn

scheduler dependency gate 必须继续保留。

## 坑 23：Event Handler 失败不能丢

失败事件要 retry，超过 max attempts 进入 dead-letter。

## 坑 24：毒事件阻塞队列

超过阈值：

```text
runtime/events/dead-letter.jsonl
```

## 坑 25：Event ordering

使用 state revision，不只看写入时间。

## 坑 26：旧任务没有 revision

缺省 0；下一次迁移写 1。

## 坑 27：旧任务 runningAt 缺失

必须兼容恢复，不能直接 crash。

## 坑 28：Pipeline BLOCKED 不能被一次 Reactor timeout 触发

区分 transient error 和 systemic error。

## 坑 29：本轮不同时改 Review 判定策略

只改“何时触发 Review”，不要同时重写 PASS/FIX 逻辑，降低风险。

## 坑 30：Independent Review anti-affinity 继续保留

不能因为事件触发快就让 implementer 自己 review。

## 坑 31：events.jsonl 无限增长

加 rotation，例如：

```text
10MB rotate
或 daily rotate
```

## 坑 32：UI cursor 和内部 cursor 分离

分别保存：

```text
runtime/event-cursors/ui-*.json
runtime/event-cursors/architect.json
runtime/event-cursors/supervisor.json
```

## 坑 33：旧 deadline entry 残留 heap

使用 generation token，不做 O(n) 删除。

## 坑 34：Supervisor 不要变成重任务执行器

Supervisor 内禁止：

```text
跑全 pytest
调用 AI
跑长 git 命令
```

巡检必须轻量。

## 坑 35：大仓库 git status 慢

给 git inspection 设 2~3 秒 timeout。

## 坑 36：SSH 巡检本身造成负担

Worker Runtime 上线前，一次巡检尽量合并为一次 SSH/一次 telemetry read。

## 坑 37：T+5 不需毫秒级精度

±5 秒完全够用。

## 坑 38：非 15 分钟 hard timeout

第一版优先支持标准 15 分钟 profile。

后续用比例：

```text
0.33 / 0.53 / 0.73 / 0.87 / 1.00 / 1.07
```

生成其他 hard timeout 的节点。

---

# 22. 测试计划

## 单测必须覆盖

```text
RUNNING T0 -> due 5/8/11/13/15/16
W1/W2 不同 start time
提前完成取消剩余 timer
retry 新 attempt 旧 timer 作废
restart recovery
review.required immediate
no-progress escalation
repeated parser error
event dedupe
review lock
event seq >100
dead letter
capacity cooldown
```

## E2E 场景 A：6 分钟完成

```text
00 RUNNING
05 healthy
06 REVIEW_REQUIRED
06 Architect review
```

不能再发生 08/11/13/15/16 巡检。

## E2E 场景 B：14 分钟完成

```text
05 healthy
08 healthy
11 on-track
13 at-risk but active
14 REVIEW_REQUIRED
14 review
```

## E2E 场景 C：第 3 分钟卡死

```text
05 no progress
08 no progress
08 supervision.alert
```

不等 15 分钟。

## E2E 场景 D：有 heartbeat 但重复 parser error

```text
05 parser error x2
08 parser error x5
```

应判 STALLED。

## E2E 场景 E：Supervisor 重启

```text
T+9 restart
```

恢复后 next stage 应是 T+11。

---

# 23. 指标

新增：

```text
architectIdleSeconds
architectBackgroundSeconds
architectReviewLatencySeconds

inspectionCount
inspectionEscalationCount
falseEscalationCount

workerIdleSeconds
workerUtilization

reviewTriggerLatency
dependencyUnlockLatency
dispatchLatency

timeoutSalvageRate
stuckDetectedBeforeHardTimeoutRate
```

关键目标：

```text
Review Trigger p95 < 2s
正常 Worker 的巡检触发 Architect 比例 < 20%
```

理想：

```text
< 10%
```

---

# 24. 四人分工

## W01 — Event / State

负责：

```text
state_events.py
core/events.py
state.py
core/state.py
seq cursor
```

## W02 — Deadline / Supervisor

负责：

```text
schedule.py
supervisor.py
recovery.py
policy.py
```

## W03 — Inspector / Runtime Integration

负责：

```text
inspector.py
progress fingerprint
error classifier
hard collect adapter
```

## W04 — Architect Reactor / QA

负责：

```text
queue.py
reactor.py
architect_loop migration
pipeline migration
tests/supervision/*
```

---

# 25. 开发 DAG

```text
EV-01 EventStore seq + append
        |
        +------------------+
        |                  |
        v                  v
EV-02 state events     SUP-01 scheduler
        |                  |
        +--------+---------+
                 v
           SUP-02 supervisor
                 |
         +-------+--------+
         |                |
         v                v
   SUP-03 inspector   AR-01 queue
         |                |
         +-------+--------+
                 v
           AR-02 reactor
                 |
                 v
           AR-03 pipeline migration
                 |
                 v
           AR-04 background scheduler
                 |
                 v
           AR-05 capacity events
                 |
                 v
           E2E / rollout
```

---

# 26. 实施顺序

## Wave 0：补 Event 基础

先做：

```text
EventStore append
seq
cursor
state event
```

不要先写 Architect Reactor。

## Wave 1：Supervisor Shadow Mode

只巡检、只记录：

```text
不改变 state
不触发 Architect
```

验证实际时间点和误报。

## Wave 2：Alert Mode

允许 supervision.alert，但 Review 仍 polling。

## Wave 3：Review Event

打开：

```text
review.required -> ArchitectReactor
```

旧 polling 仍 fallback，但必须有 review lock。

## Wave 4：关闭 Architect polling

确认稳定后：

```text
architectPollingReview=false
```

## Wave 5：capacity / background

最后再开启：

```text
capacity.available
architect background
```

---

# 27. Feature Flags

建议：

```json
{
  "supervisionEnabled": true,
  "supervisionShadowMode": true,
  "architectEventReview": false,
  "architectPollingReview": true,
  "architectBackgroundEnabled": false,
  "capacityEventsEnabled": false
}
```

上线顺序：

```text
1 shadow=true
2 alert
3 architectEventReview=true
4 architectPollingReview=false
5 background=true
6 capacity=true
```

---

# 28. 回滚

任何异常：

```text
supervisionEnabled=false
architectEventReview=false
architectPollingReview=true
```

即可回旧 pipeline。

旧 loop 至少保留一个版本周期。

---

# 29. Definition of Done

```text
[ ] 每个 Worker 从自己的 RUNNING 时间独立计时
[ ] 默认巡检点为 T+5/8/11/13/15/16
[ ] Worker 提前完成后剩余巡检自动取消
[ ] 正常巡检不调用 Architect
[ ] REVIEW_REQUIRED 2 秒内进入 ArchitectQueue
[ ] 同一个 review 不会执行两次
[ ] Supervisor restart 后 timer 可恢复
[ ] 新 attempt 不受旧 timer 影响
[ ] EventStore >100 事件不会丢 cursor
[ ] EventStore append 不再 O(n) 重写全文件
[ ] heartbeat 新鲜但重复错误可识别 stalled
[ ] T+15 自动 hard collect
[ ] T+16 自动清理 orphan RUNNING
[ ] capacity.available 有 cooldown
[ ] Architect 背景任务受最大时长限制
[ ] 关闭 polling review 后全链路正常
[ ] Feature Flag 可一键回滚
```

---

# 30. 最终行为示例

4 个 Worker：

```text
15:00 W01 开始
15:02 W02 开始
15:04 W03 开始
15:07 W04 开始
```

Supervisor：

```text
15:05 W01 C1
15:07 W02 C1
15:08 W01 C2
15:09 W03 C1
15:10 W02 C2
15:11 W01 C3
15:12 W04 C1
...
```

Architect 不参与正常 C1/C2。

假设 W01 15:06 完成：

```text
15:06 review.required
15:06 Architect 被唤醒
```

W01 后续 08/11/13/15/16 全部取消。

假设 W02 parser loop：

```text
15:07 C1 发现重复错误
15:10 C2 再次无进展
15:10 supervision.alert
```

不等硬超时。

---

# 31. 最终目标

改造前：

```text
Architect
    ↓
每几秒扫描任务
    ↓
看 Worker
    ↓
没完成
    ↓
继续等
```

改造后：

```text
Architect
    ↓
干真正需要架构决策的事情

Supervisor
    ↓
负责时间和巡检

Worker
    ↓
负责执行

Event Bus
    ↓
真正需要时再叫 Architect
```

最终目标不是“巡检更聪明”，而是：

> **正常情况下 Architect 根本不需要巡检。5/3/3/2/2/1 只是后台 Supervisor 的保险丝；Worker 一完成就主动敲门，Worker 一卡住就自动报警，Worker 空闲就自动补充可并行工作。**
