# CodeartsBridge AI 收口 / 产品化工作区

> 作用：后续 AI/Coding Agent 的第一入口文档。  
> 当前基线：`main@e1db59b`。  
> 当前阶段已经从“架构收口”转入“收口尾声 + 产品化/UI”。

## 0. 当前真实主链

已经成立并应冻结：

```
任务创建
  -> auto_dispatch + scheduler
  -> Worker Agent
  -> CodeArts CLI
  -> 实时 reasoning/tool/event
  -> outbox archive
  -> Bridge fetch
  -> REVIEW_REQUIRED
  -> APPROVED
  -> real integration
  -> DONE + integratedSha
```

Issue #38 已解决并关闭。Agent 是当前核心 Worker runtime，不再作为删除候选。

Web UI 不承担执行控制（cancel/retry/review/integrate），但允许“删除任务记录”这一项管理动作。Delete 与 Cancel 必须分离。

## 1. AI 开工前必须遵守

1. 先读 `NEXT.md` 和 `07-PRODUCTIZATION-ROADMAP.md`。
2. 不新增“大而全”架构，不新造抽象层解决旧抽象层问题。
3. Agent / Scheduler / Lifecycle / Integration 主链没有真实 field bug 时保持冻结。
4. 一个功能只有满足“入口 -> 实际调用 -> 状态变化 -> 可观察结果 -> E2E”才算存在。
5. 两套实现解决同一件事时，选一套 canonical path，删除另一套。
6. 删除优先于适配。
7. 不恢复已删除的 policy / supervision / runtime supervisor / daemon / adaptive / cost。
8. UI 以可观察和日常效率为主，不恢复第二控制平面。
9. 测试通过不能替代真实链路验证。
10. 文档必须和 main 当前行为一致，避免下一位 Agent 按旧设计重复施工。

## 2. 当前阶段目标

```
P0  清理 CLI / packaging 死入口              ✅
P1  Tasks / Task Detail 好用                  ✅
P1  Thinking / Overview 好用                  ⏳
P2  删除 legacy integration 平行路径           ✅
P2  是否把唯一 TaskLoop 收进 bridge serve      ⏳
08  DELETE API + deferred delete + UI 删除     ✅
P3  README / deploy / runtime truth 最终同步   ⏳
```

详细安排：

```
07-PRODUCTIZATION-ROADMAP.md
```

## 3. 已完成的重要收口

```
Review PASS 只到 APPROVED
真实 Integration 后才 DONE
dispatch 主路径统一到 auto_dispatch + scheduler
Agent JSON PIPE / Watchdog / Recovery / artifact fetch 已实跑
Issue #38 P0-A/P0-B 已闭环
supervision / policy / runtime / dispatch / daemon / adaptive / cost 主模块已删除
legacy integration_service.py 已删除，API/MCP 统一用 canonical integrate_task
DELETE /api/tasks/<taskId> 已实现（08-TASK-DELETION-SEMANTICS）
UI localStorage 隐藏已替换为真正删除
Python 3.11 / 3.12 / 3.13 CI 全绿
```

## 4. CodeArts write 限制

当前现场结论：

```
write/edit/dotfile permission = allow
5 分钟 permission hang 已消失
--format json 下 built-in write/edit 仍可能立即拒绝
bash fallback 可可靠写入 outbox
```

这是已知 CodeArts CLI 行为，不再作为 Bridge P0。

不要重新搬 outbox、改共享目录或重写 Agent artifact 系统来追这个限制。

## 5. UI 当前真相

任务删除已实现（08-TASK-DELETION-SEMANTICS）：

```
DELETE /api/tasks/<taskId>
  200 {"deleted": true}   — 立即物理删除
  202 {"pending": true}   — 延迟删除（运行中，marker 已写）

.delete-requested marker → scanners 跳过 → 完成后 finalize 物理删除
终态任务残留 inflight.json 不阻止删除
```

UI 不做执行控制（cancel/retry/review/integrate），但允许删除任务记录。

## 6. 文档阅读顺序

```
NEXT.md
07-PRODUCTIZATION-ROADMAP.md
08-TASK-DELETION-SEMANTICS.md
05-REAL-ACCEPTANCE.md
06-AGENT-RUNTIME-TRUTH.md   # 作为问题历史与约束参考，不再是待办
01-RUNTIME-TRUTH.md         # 历史审计，不代表当前完整状态
02-CLOSEOUT-ROADMAP.md      # 历史收口计划
03-DELETE-OR-WIRE-MATRIX.md # 历史删除依据
04-AI-EXECUTION-RULES.md
```

旧文档和当前代码冲突时，以 `NEXT.md`、`07-PRODUCTIZATION-ROADMAP.md` 和当前 main 为准。
