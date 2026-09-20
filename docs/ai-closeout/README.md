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
/docs/CODEARTS-PINNED-RUNTIME.md
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

## CodeArts 运行时固定规则

当前实验室生产 Worker 固定使用：

```text
CodeArts CLI 26.8.12
```

恢复包已上传到 GitHub Release `codearts-cli-26.8.12-pinned`，SHA-256 与安装步骤见 `docs/CODEARTS-PINNED-RUNTIME.md`。

26.9.7 在现有账号上会在 Model Queuing 阶段被 package/account gate 拒绝，因此不要在生产 Worker 执行 `codearts upgrade`。

## 已解决的 CodeArts write 配置问题

26.8.12 固定基线上的 built-in write 已通过项目内、项目外、默认 Agent、显式 Build、`--auto` 和 Agent HTTP 真实任务验证。

根因是 CLI 真实 data path 下的权限仍为 `ask`，以及旧 Agent 继承 `OPENCODE_*` 指向旧配置。后续部署必须运行 `deploy/codearts-worker-runtime.py audit`；完整报告见 `docs/CODEARTS-WRITE-PERMISSION-RUNBOOK.md`。

shell fallback 仍是应急路径，不是部署验收标准。不要因此重构 Agent/outbox。

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
