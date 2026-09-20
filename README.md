# CodeartsBridge

多 Worker 软件开发控制平面。Bridge 负责创建/调度任务、实时观察、审查与集成；Worker Agent 在各节点启动本机 CodeArts CLI，并把事件与成果回传给 Bridge。

> **AI / Coding Agent：先读 [AGENTS.md](AGENTS.md)。**
>
> **安装、配置、升级、排障：读 [docs/USAGE.md](docs/USAGE.md)。**
>
> **CodeArts Worker 当前固定使用 26.8.12：读 [docs/CODEARTS-PINNED-RUNTIME.md](docs/CODEARTS-PINNED-RUNTIME.md)。**

## AI 快速接管

如果你是第一次进入仓库的 AI / Coding Agent，先按这个顺序做，不要直接升级或重装：

1. 读 `AGENTS.md`、本文件和 `docs/USAGE.md`。
2. 用 `git status --short`、`git rev-parse HEAD` 确认正在看的 checkout。
3. 区分三个位置：CodeartsBridge 控制代码、Worker 的目标 `projectRoot`、Agent 自己的数据目录；它们不是同一个目录。
4. 读 `projects.json` 和 `workers.json`，不要把实验室 IP 或路径写死到代码。
5. 先检查 Bridge `:8080` 和四个 Agent `:8765` 的健康，再创建任务。
6. 在每台 Worker 运行 CodeArts runtime audit；只有全部 `PASS` 才能判断部署正常。
7. 涉及 write/edit 时必须跑真实 Agent Job；shell/Python fallback 不算原生 write 验收通过。
8. 任务完成以 outbox 交付物、review 和真实 integration 为准，不以进程退出码或 UI 动画为准。

当前实验室部署快照最后核验于 **2026-09-20**：

| 项目 | 当前值 |
|---|---|
| Bridge | `192.168.178.50:8080` |
| Worker Agent | `192.168.178.50` 至 `.53`，端口 `8765` |
| CodeArts CLI | 四台固定 `26.8.12`，禁止自动升级 |
| Agent 服务 | 当前四台使用用户级 `bridge-worker-agent.service`，检查时用 `systemctl --user` |
| Agent runtime checkout | `/home/nathan/codeartsbridge-runtime-5bda01d` |
| 默认目标项目 | `/home/nathan/bridge-python` |
| Agent 数据目录 | `/home/nathan/.codex-glm-bridge/agent` |
| CodeArts 生效数据目录 | `/home/nathan/.local/share/opencode` |
| Native write | 四台真实 Agent Job 均为 `COMPLETED`、exit `0`、`write → read`、无 fallback |

这是一个已验证快照，不是永久硬编码。操作前仍要以 live health、systemd scope、当前 Git commit 和 `codearts debug paths` 为准。

## 当前主链

```text
Task
→ auto_dispatch + scheduler
→ Worker Agent
→ CodeArts CLI
→ live reasoning/tool events
→ outbox archive
→ Bridge fetch
→ REVIEW_REQUIRED
→ APPROVED
→ integration
→ DONE + integratedSha
```

正常使用 **Agent transport**。不要从历史文档恢复已经删除的 daemon / policy / supervision / 第二套 runtime。

## 5 分钟启动

### 1. Bridge 主机

```bash
git clone https://github.com/nathanxiangang-web/CodeartsBridge.git
cd CodeartsBridge
./deploy/install-bridge.sh
```

默认安装并启动：

```text
bridge.service
bridge serve --host 0.0.0.0 --port 8080 --with-pipeline
```

UI：

```text
http://<bridge-host>:8080
```

### 2. 每台 Worker

Worker 必须先满足：

```bash
codearts --version
# expected: 26.8.12
```

当前不要在生产 Worker 执行 `codearts upgrade`。26.8.12 恢复包已经上传到 Release `codearts-cli-26.8.12-pinned`。

然后：

```bash
git clone https://github.com/nathanxiangang-web/CodeartsBridge.git
cd CodeartsBridge
BRIDGE_AGENT_AUTH=off \
BRIDGE_CODEARTS_EXPECTED_VERSION=26.8.12 \
./deploy/install-worker-agent.sh
```

安装脚本安装的是系统级 systemd unit，并要求 Python venv 可用和 sudo。当前实验室四台运行的是用户级 unit；维护现有部署时先读 `docs/USAGE.md` 的“当前实验室运行真相”，不要在未确认迁移范围时直接覆盖。

默认安装并启动：

```text
bridge-worker-agent.service
Agent HTTP :8765
```

新安装默认可信 LAN、auth off；不会自动生成一个 Bridge 不知道的 token。显式使用 `BRIDGE_AGENT_AUTH=off` 时，生成的 unit 也不会加载 `agent.env`，并会清除父环境残留的 `BRIDGE_AGENT_TOKEN`。

### 3. 配置

`projects.json`：

```json
{
  "projects": [
    {
      "id": "bridge",
      "transport": "agent",
      "projectRoot": "/home/nathan/bridge-python"
    }
  ]
}
```

`workers.json`：

```json
{
  "workers": [
    {
      "id": "w01",
      "transport": "agent",
      "endpoint": "http://192.168.178.52:8765",
      "enabled": true
    }
  ]
}
```

`projectRoot` 是 **Worker 本机** 项目路径。每台 Worker 都必须存在这个目录。

当前仓库里的 `workers.json` 配置了 4 个实验室 Worker；不要在代码里硬编码这些地址。

### 4. 创建任务

```bash
cat >/tmp/task.md <<'EOF'
# Objective
Fix the target bug.

# Required Changes
- Make the scoped code change.
- Add/update focused tests.

# Acceptance Criteria
- Focused tests pass.
- No unrelated changes.
EOF

bridge create -p bridge -t my-task --task-file /tmp/task.md
```

如果 Bridge 以 `--with-pipeline` 运行，任务会进入自动 dispatch/review/integrate 主循环。

手动模式：

```bash
bridge auto-dispatch
bridge status
bridge review-pass -t my-task
bridge integrate --task-id my-task
```

## 运行方式

### 推荐：自治服务

```bash
bridge serve --host 0.0.0.0 --port 8080 --with-pipeline
```

### 只启动 API/UI

```bash
bridge serve --host 0.0.0.0 --port 8080
```

此时需要手动：

```bash
bridge auto-dispatch
# 或
bridge pipeline --once
```

## Web UI

| 页面 | 用途 |
|---|---|
| Overview | Worker online/busy、任务计数、运行信息 |
| Tasks | 任务筛选、状态、时间、删除任务记录 |
| Task Detail | outbox、RESULT/TESTS/DIFF、commit、事件时间线 |
| Thinking | 实时 Agent thinking 与历史输出 |

任务删除语义：

```text
Delete != Cancel
```

删除正在运行的任务记录不会取消 Agent / CodeArts；运行继续，Bridge 在安全时机 deferred cleanup。

## Worker / Agent

Agent 负责：

- 启动 CodeArts CLI
- stdout/stderr JSON pipe
- watchdog / timeout
- restart recovery
- live events
- outbox archive
- artifact fetch

Agent 健康检查：

```bash
curl -fsS http://<worker>:8765/v1/health
```

Bridge 健康检查：

```bash
curl -fsS http://<bridge-host>:8080/api/health
```

## CodeArts 固定版本与 write/edit 当前说明

当前实验室 Worker **固定使用 CodeArts CLI 26.8.12**。26.9.7 在现有账号上会在 Model Queuing 阶段被 package/account gate 拒绝，因此不能当作可升级版本。恢复包、SHA-256 和安装步骤见 [docs/CODEARTS-PINNED-RUNTIME.md](docs/CODEARTS-PINNED-RUNTIME.md)。

这和 built-in write/edit 是两个独立问题。26.8.12 的原生 write 已确认可用；此前拒绝来自错误的生效权限文件和 Agent 遗留 `OPENCODE_*` 环境。部署时运行：

```bash
python3 deploy/codearts-worker-runtime.py audit \
  --expected-version 26.8.12 \
  --require-aksk
```

看到 shell/python fallback 不能代替原生 write 验收。完整证据、修复与回滚见 [docs/CODEARTS-WRITE-PERMISSION-RUNBOOK.md](docs/CODEARTS-WRITE-PERMISSION-RUNBOOK.md)。

原生 write 的最小成功证据必须同时满足：

```text
Agent Job = COMPLETED
exitCode = 0
events 中出现 write（最好随后 read 回读）
目标文件内容正确
没有 bash/python fallback
```

## 常用 CLI

| 命令 | 作用 |
|---|---|
| `bridge bootstrap` | 初始化 runtime/task 目录 |
| `bridge doctor` | 检查配置与环境 |
| `bridge status` | 查看任务 |
| `bridge create ...` | 创建任务 |
| `bridge auto-dispatch` | 自动派发 READY 任务 |
| `bridge pipeline` | review/dispatch/integrate 循环 |
| `bridge serve` | API/UI/MCP；可加 `--with-pipeline` |
| `bridge review-pass -t ID` | 审查通过 |
| `bridge review-fix -t ID --fix-file FILE` | 请求修复 |
| `bridge integrate --task-id ID` | 集成 APPROVED 任务 |
| `bridge cancel -t ID` | 取消任务执行 |
| `bridge workers` | 查看 Worker |
| `bridge projects` | 查看 Project |

完整参数以：

```bash
bridge --help
bridge <command> --help
```

为准。

## 安装/升级脚本

```text
deploy/install-bridge.sh
deploy/install-worker-agent.sh
```

升级：

```bash
git pull --ff-only
./deploy/install-bridge.sh        # Bridge 主机
BRIDGE_AGENT_AUTH=off BRIDGE_CODEARTS_EXPECTED_VERSION=26.8.12 ./deploy/install-worker-agent.sh  # Worker
```

部署目录说明见 [deploy/README.md](deploy/README.md)。

## 开发验证

```bash
python -m pytest -q
python -m bridge.cli --help
python -m bridge.cli doctor
```

修改 Agent / transport / lifecycle 后，必须额外跑真实 task，不能只靠单元测试。

## 文档入口

- [AGENTS.md](AGENTS.md) — AI / 新维护者第一入口
- [docs/USAGE.md](docs/USAGE.md) — 当前使用与运维手册
- [docs/CODEARTS-PINNED-RUNTIME.md](docs/CODEARTS-PINNED-RUNTIME.md) — 固定 CodeArts 26.8.12 与恢复规则
- [docs/CODEARTS-WRITE-PERMISSION-RUNBOOK.md](docs/CODEARTS-WRITE-PERMISSION-RUNBOOK.md) — CodeArts write 权限核查与恢复
- [docs/ai-closeout/NEXT.md](docs/ai-closeout/NEXT.md) — 当前下一步
- [protocol/WORKER.md](protocol/WORKER.md) — 注入 Worker 的执行契约

历史设计/收口文档仍保留用于追溯，但与当前 main 冲突时，以代码、`AGENTS.md`、`docs/USAGE.md` 为准。

## License

MIT
