# CodeartsBridge AI 工作区

> 当前项目已经完成主要架构收口，正在进入日常使用 / UI / 运维完善阶段。
>
> **新的 AI / Coding Agent 不要从本目录的历史 roadmap 猜当前架构。**

## 第一入口

先读：

```text
/AGENTS.md
/README.md
/docs/USAGE.md
/docs/ai-closeout/NEXT.md
```

这四份是当前使用真相。

## 当前主链

```text
Task
→ auto_dispatch + scheduler
→ Worker Agent
→ CodeArts CLI
→ live events
→ outbox archive
→ Bridge fetch
→ REVIEW_REQUIRED
→ APPROVED
→ canonical integration
→ DONE
```

Agent transport 是当前核心，不是待删除候选。

## 当前运行方式

Bridge：

```bash
bridge serve --with-pipeline
```

Worker：

```bash
python -m bridge.agent.cli --listen 0.0.0.0 --port 8765
```

安装统一走：

```text
deploy/install-bridge.sh
deploy/install-worker-agent.sh
```

详细见 `docs/USAGE.md`。

## 已经完成、不要重做

- dispatch 主路径统一到 `auto_dispatch + scheduler`
- Review PASS 只到 APPROVED
- 真实 Integration 后才 DONE
- Agent JSON pipe / watchdog / recovery / archive/fetch 已实跑
- artifact archive-before-COMPLETED 顺序已修
- supervision / policy / 第二套 runtime / daemon / adaptive / cost 主模块已删除
- legacy `application/integration_service.py` 已删除
- Task DELETE 已实现，运行中采用 deferred delete
- Tasks / Task Detail 已完成第一轮产品化

## 当前已知未决

CodeArts `--format json` 下 built-in `write/edit` 仍可能立即拒绝。

当前 Worker 会使用 shell fallback 写正式 outbox，所以任务可以交付；但不要把 fallback 误写成“built-in write 已修复”。

调查这个问题时，先做可复现实验，不要先重构 Agent/outbox。

## UI 边界

UI 可以：

- 查看任务/Worker
- 查看成果/日志
- 删除任务记录

UI 不承担：

- cancel
- retry
- reassign
- review pass/fix
- integrate

Delete 与 Cancel 必须分离。

## 历史文档

以下文档用于理解历史决策：

```text
01-RUNTIME-TRUTH.md
02-CLOSEOUT-ROADMAP.md
03-DELETE-OR-WIRE-MATRIX.md
04-AI-EXECUTION-RULES.md
05-REAL-ACCEPTANCE.md
06-AGENT-RUNTIME-TRUTH.md
07-PRODUCTIZATION-ROADMAP.md
08-TASK-DELETION-SEMANTICS.md
```

它们与当前代码/ `AGENTS.md` / `docs/USAGE.md` 冲突时，以当前代码和新入口文档为准。
