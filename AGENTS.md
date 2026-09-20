# AGENTS.md — CodeartsBridge 开工入口

> 给任何 Coding Agent / AI / 新维护者：**先读这个文件，再改代码。**
>
> CodeartsBridge 不是一个普通 Python 库。它是一个多 Worker 软件开发控制平面：Bridge 负责任务、调度、审查、集成和 UI；每台 Worker 运行 Agent，Agent 再启动本机 CodeArts CLI。

## 1. 一句话理解

正常运行链只有这一条：

```text
Task
→ Bridge scheduler / pipeline
→ Worker Agent (:8765)
→ CodeArts CLI
→ live events
→ outbox artifacts
→ REVIEW_REQUIRED
→ APPROVED
→ real integration
→ DONE
```

当前架构的核心是 **Agent transport**。不要因为看到旧文档或旧脚本，就恢复 SSH/daemon/policy/supervision 等已经收掉的旧路径。

## 2. 先读什么

按这个顺序：

1. `README.md` — 项目是什么、5 分钟启动
2. `docs/USAGE.md` — 安装、配置、日常操作、升级、排障
3. `docs/CODEARTS-PINNED-RUNTIME.md` — CodeArts 26.8.12 固定版本与恢复规则
4. `docs/ai-closeout/NEXT.md` — 当前下一步
5. `docs/ai-closeout/README.md` — 当前架构约束
6. `protocol/WORKER.md` — 注入给 Worker/CodeArts 的执行契约

`docs/ai-closeout/01~08` 中有历史审计和收口记录。它们用于理解“为什么这样设计”，不是默认待办清单。

**当前实验室 CodeArts CLI 固定为 26.8.12。不要升级到 26.9.x 或其他未知版本。** 恢复包已经作为 GitHub Release `codearts-cli-26.8.12-pinned` 上传，详见 `docs/CODEARTS-PINNED-RUNTIME.md`。

## 3. 当前运行方式

### Bridge 主机

推荐长期运行：

```bash
bridge serve --host 0.0.0.0 --port 8080 --with-pipeline
```

它提供：

- HTTP API
- Web UI
- SSE 实时事件
- MCP
- 可选 in-process pipeline（dispatch / review / integrate）

不带 `--with-pipeline` 时，Bridge 只提供服务面；任务需要手动 `bridge auto-dispatch` / `bridge pipeline`。

### Worker

每台 Worker 长期运行：

```bash
python -m bridge.agent.cli --listen 0.0.0.0 --port 8765
```

正常部署使用 systemd，由：

```bash
./deploy/install-worker-agent.sh
```

安装。

当前实验室四台 Agent 最后核验于 2026-09-20，使用的是用户级 systemd unit，而安装脚本默认创建系统级 unit。维护现有部署时先用下面两条命令识别 scope，不要盲目覆盖：

```bash
systemctl --user is-enabled bridge-worker-agent.service || true
systemctl is-enabled bridge-worker-agent.service || true
```

当前用户级 Agent runtime 是 `/home/nathan/codeartsbridge-runtime-5bda01d`；`/home/nathan/bridge-python` 是任务目标项目，不是同一职责。

Worker 本机必须满足：

- Python 3.10+
- 当前项目代码已 checkout
- 目标 `projectRoot` 在本机存在
- `codearts --version` 能正常执行并返回 **26.8.12**
- Bridge 能访问 `http://<worker>:8765`

## 4. 当前仓库配置

配置文件在仓库根目录：

```text
projects.json
workers.json
```

当前实验室配置是 4 个 Worker：

```text
w01 -> 192.168.178.52:8765
w02 -> 192.168.178.50:8765
w03 -> 192.168.178.53:8765
w04 -> 192.168.178.51:8765
```

不要在代码里硬编码这些地址；只通过配置读取。

## 5. 创建和运行任务

任务说明写成 Markdown 文件，例如：

```markdown
# Objective
Fix the task list rendering bug.

# Required Changes
- Fix the bug.
- Add or update focused tests.

# Acceptance Criteria
- Focused tests pass.
- No unrelated changes.
```

创建：

```bash
bridge create -p bridge -t fix-task-list --task-file /tmp/fix-task-list.md
```

自动模式：

```bash
bridge serve --with-pipeline
```

手动单步：

```bash
bridge auto-dispatch
bridge status
bridge review-pass -t fix-task-list
bridge integrate --task-id fix-task-list
```

UI：

```text
http://<bridge-host>:8080
```

## 6. 任务删除语义

非常重要：

```text
Delete != Cancel
```

UI 删除任务记录时：

- 已结束任务可以直接物理删除
- 正在运行的任务 **不能因为 Delete 被 cancel / kill**
- 运行中的删除采用 deferred delete：UI 立即移除，真实 Worker 继续，结束后 Bridge 再清理 task 记录

详细见：

```text
docs/ai-closeout/08-TASK-DELETION-SEMANTICS.md
```

## 7. Agent / CodeArts 当前已知事实

Agent 是当前核心运行时，承担：

- CodeArts 进程生命周期
- JSON pipe
- watchdog
- recovery
- live event
- outbox archive
- artifact fetch

Issue #38 已修复过“5 分钟 permission hang”和“COMPLETED 早于 archive”的问题。

当前还必须遵守版本固定规则：

- 实验室生产 Worker 使用 **26.8.12 pinned runtime**
- 26.9.7 在现有账号上会在 Model Queuing 阶段被 package/account gate 拒绝
- 不要把 26.9.7 的 Access denied 诊断成 Bridge / outbox / write 问题
- 不要在生产 Worker 执行 `codearts upgrade`

CodeArts built-in `write/edit` 已在 26.8.12 固定基线上完成受控排查：

- 当前 CLI 的真实 data path 必须以 `codearts debug paths` 为准
- 当前实验室生效权限文件位于 `~/.local/share/opencode/storage/permission/global.json`
- `edit/write/external_directory_write/dotfile` 必须是 `allow`
- Agent 进程不能继承旧 `OPENCODE_*` 环境
- 默认 Agent、显式 Build、`--auto` 和 Agent HTTP 真实 Job 均已验证原生 write 成功
- shell/python fallback 仍是应急路径，但不能代替原生 write 的部署验收

完整证据、核查、修复与回滚见 `docs/CODEARTS-WRITE-PERMISSION-RUNBOOK.md`。

## 8. 修改项目时的硬规则

不要恢复已经删除的：

```text
bridge-daemon
supervision/
policy/
runtime supervisor
adaptive scheduler
cost layer
旧 dispatch.py
```

不要新造第二套：

- scheduler
- lifecycle state machine
- review state machine
- integration path
- Agent supervisor

当前 canonical integration 是 `src/bridge/integration.py`。

UI 可以做任务记录管理，但不要重新变成一个重型执行控制台。

## 9. 提交前最小验证

至少执行：

```bash
python -m pytest -q
python -m bridge.cli --help
python -m bridge.cli doctor
```

如果改了部署 / Agent：

```bash
curl -fsS http://127.0.0.1:8765/v1/health
```

如果改了 Bridge API/UI：

```bash
curl -fsS http://127.0.0.1:8080/api/health
```

如果改了真实执行链，单元测试不够，必须跑一个真实 task。

## 10. 文档真相优先级

发生冲突时，优先级：

```text
当前 main 代码
> AGENTS.md
> docs/USAGE.md
> docs/CODEARTS-PINNED-RUNTIME.md
> docs/ai-closeout/NEXT.md
> docs/ai-closeout/README.md
> 历史 roadmap / audit 文档
```

不要根据历史文档重新实现已经删除的架构。
