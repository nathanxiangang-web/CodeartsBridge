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

## CodeArts editor 当前状态

26.8.12 固定运行时上的 built-in `write/edit` 已完成权限修正和多 Worker 实机验证；临时 `WRITE_STRATEGY_DIRECTIVE` 已删除，built-in editor 重新成为正常执行路径。

shell/python 写入只应作为异常兜底。若 editor refusal 回归，先检查单机 CodeArts 权限、目标路径和版本漂移，不要重新设计 Agent/outbox。

仍未解决的是 **26.9.7 的 package/account routing**，它发生在 Model Queuing 阶段，与 editor 问题无关。

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
