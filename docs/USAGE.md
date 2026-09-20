# CodeartsBridge 使用与运维手册

> 这是当前运行手册。适用于人类维护者和 Coding Agent。
>
> 快速理解项目先读仓库根目录 `AGENTS.md`。

## 0. AI 操作入口

AI / Coding Agent 接管本项目时，先建立下面四个事实，再做任何变更：

```text
1. 我正在修改哪个 Git checkout / commit？
2. Bridge 和 Worker Agent 当前是否健康？
3. 当前服务是 system scope 还是 user scope？
4. CodeArts 实际版本、data path、权限和进程环境是什么？
```

最小只读检查：

```bash
git status --short
git rev-parse HEAD
cat projects.json
cat workers.json
curl -fsS http://192.168.178.50:8080/api/health
```

每台 Worker：

```bash
codearts --version
curl -fsS http://127.0.0.1:8765/v1/health

if systemctl --user is-enabled bridge-worker-agent.service >/dev/null 2>&1; then
  systemctl --user --no-pager --full status bridge-worker-agent.service
else
  sudo systemctl --no-pager --full status bridge-worker-agent.service
fi

python3 deploy/codearts-worker-runtime.py audit \
  --expected-version 26.8.12 \
  --require-aksk
```

安全边界：

- 不输出或提交 AK/SK、Agent token、私钥。
- 不在生产 Worker 执行 `codearts upgrade`。
- 不把 shell/Python fallback 当成 built-in write 已修复的证据。
- 不因为 `exit 0` 就宣告任务完成；必须检查 outbox、测试、diff、review 和 integration。
- 不把 CodeartsBridge runtime checkout 与 `projects.json` 中的目标 `projectRoot` 混为一谈。

### 0.1 当前实验室运行真相

最后核验：**2026-09-20**。

| 项目 | 当前状态 |
|---|---|
| Bridge host | `192.168.178.50` |
| Workers | `192.168.178.50/51/52/53:8765` |
| Worker service scope | 用户级 systemd，unit 为 `~/.config/systemd/user/bridge-worker-agent.service` |
| Linger | 四台 `nathan` 用户均为 `Linger=yes` |
| Agent runtime checkout | `/home/nathan/codeartsbridge-runtime-5bda01d`，部署提交 `5bda01d` |
| 目标项目 | `/home/nathan/bridge-python` |
| Agent data root | `/home/nathan/.codex-glm-bridge/agent` |
| CodeArts executable | `/home/nathan/.codeartsdoer/installers/bin/codearts`，全局 `/usr/local/bin/codearts` 已指向它 |
| CodeArts version | `26.8.12` |
| Credential file | `~/.config/codeartsbridge/codearts.env`，mode `600` |
| Effective CodeArts data dir | `~/.local/share/opencode` |
| Native write evidence | 四台 Agent Job 均为 `COMPLETED`、exit `0`、`write → read`、文件正确、无 fallback |

当前 Agent 的常用操作必须使用用户级命令：

```bash
systemctl --user status bridge-worker-agent
systemctl --user restart bridge-worker-agent
journalctl --user -u bridge-worker-agent -f
```

仓库安装脚本当前创建的是系统级 service。它适合满足 `python3-venv` 和 sudo 前置条件的新安装；它不是当前四台用户级部署的无差别覆盖命令。迁移 service scope 前，先记录当前 unit、运行目录、环境文件和回滚方式。

## 1. 运行拓扑

```text
                    Bridge Host
             +----------------------+
             | bridge serve :8080   |
             | API / UI / SSE / MCP |
             | pipeline (optional)  |
             +----------+-----------+
                        |
                 HTTP Agent API
        +---------------+---------------+
        |               |               |
   Worker w01       Worker w02      Worker w03/w04
   Agent :8765      Agent :8765      Agent :8765
        |               |               |
     CodeArts         CodeArts         CodeArts
```

Bridge 不直接通过 SSH 启动 CodeArts。正常生产路径是 Agent HTTP transport。

## 2. 前置条件

Bridge 主机：

- Linux
- Python 3.10+
- Git
- 能访问所有 Worker 的 8765 端口

每台 Worker：

- Linux
- Python 3.10+
- Git
- CodeArts CLI 已安装并配置
- `codearts --version` 能在运行 Agent 的用户下成功，并且当前必须是 **26.8.12**
- 目标项目已经 checkout 到 `projects.json` 里的 `projectRoot`

新安装建议所有机器上的 CodeartsBridge 仓库使用同一路径。当前实验室需要明确区分：

```text
/home/nathan/codeartsbridge-runtime-5bda01d  # Agent 运行时代码
/home/nathan/bridge-python                   # Worker 被操作的目标项目
```

代码本身不依赖这两个固定路径；以 live unit 的 `WorkingDirectory`、`PYTHONPATH` 和 `projects.json` 为准。

## 3. 第一次安装

### 3.1 Bridge 主机

```bash
git clone https://github.com/nathanxiangang-web/CodeartsBridge.git
cd CodeartsBridge

./deploy/install-bridge.sh
```

安装脚本会：

1. 创建 `.venv`
2. `pip install -e .`
3. 执行 `bridge bootstrap`
4. 执行 `bridge doctor`
5. 安装并启动 `bridge.service`
6. 默认使用 `bridge serve --with-pipeline`

默认：

```text
listen = 0.0.0.0
port = 8080
pipeline = on
```

可覆盖：

```bash
BRIDGE_PORT=8088 ./deploy/install-bridge.sh
BRIDGE_WITH_PIPELINE=0 ./deploy/install-bridge.sh
BRIDGE_INSTALL_SYSTEMD=0 ./deploy/install-bridge.sh
```

### 3.2 Worker

当前 Worker CodeArts 运行时是 **固定版本 26.8.12**。不要先安装/升级最新版。若机器已经被升级到 26.9.x，先按 `docs/CODEARTS-PINNED-RUNTIME.md` 恢复 26.8.12。

每台 Worker：

```bash
git clone https://github.com/nathanxiangang-web/CodeartsBridge.git
cd CodeartsBridge

codearts --version
# expected: 26.8.12
BRIDGE_CODEARTS_EXPECTED_VERSION=26.8.12 ./deploy/install-worker-agent.sh
```

安装脚本会：

1. 创建/更新 `.venv`
2. editable install 当前仓库
3. 创建 Agent data root
4. 创建 `~/.config/codeartsbridge/agent.json`
5. 安装并启动 `bridge-worker-agent.service`
6. 检查 `/v1/health`

CodeArts AK/SK 使用独立文件 `~/.config/codeartsbridge/codearts.env`，权限必须是 `600`。该文件不提交仓库，安装器只加载和保留它。生成的 systemd unit 会禁用 CodeArts 自动升级并清除旧 `OPENCODE_*` 环境。

新安装默认是可信 LAN 模式，不自动生成 token。

如果已有 `~/.config/codeartsbridge/agent.env`，默认 `auto` 模式会保留它。旧安装若留下了 Bridge 未配置的 token，可明确关闭：

```bash
BRIDGE_AGENT_AUTH=off ./deploy/install-worker-agent.sh
```

如需 token 模式：

```bash
BRIDGE_AGENT_AUTH=token BRIDGE_AGENT_TOKEN='...' ./deploy/install-worker-agent.sh
```

此时 Bridge 侧也必须配置匹配 token；否则 job API 会返回 401。

## 4. 配置

### 4.1 projects.json

格式：

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

字段：

| 字段 | 说明 |
|---|---|
| `id` | 项目 ID，创建任务时用 `-p` 指定 |
| `transport` | 正常使用 `agent` |
| `projectRoot` | Worker 本机上的项目绝对路径 |
| `runMode` | 可选，默认 `auto` |
| `model` | 可选，默认由当前配置决定 |

### 4.2 workers.json

格式：

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

字段：

| 字段 | 说明 |
|---|---|
| `id` | Worker ID |
| `transport` | 正常使用 `agent` |
| `endpoint` | Agent HTTP 地址 |
| `enabled` | 是否参与调度 |
| `concurrencyLimit` | 可选，默认 1 |
| `capabilities` | 可选，角色能力 |
| `cliPath` | 可选，指定 CodeArts CLI 路径 |

修改配置后，建议：

```bash
bridge doctor
bridge workers
bridge projects
```

## 5. 启动与检查

### Bridge

```bash
sudo systemctl status bridge
curl -fsS http://127.0.0.1:8080/api/health
```

日志：

```bash
journalctl -u bridge -f
```

### Worker

```bash
curl -fsS http://127.0.0.1:8765/v1/health

if systemctl --user is-enabled bridge-worker-agent.service >/dev/null 2>&1; then
  systemctl --user status bridge-worker-agent
  journalctl --user -u bridge-worker-agent -f
else
  sudo systemctl status bridge-worker-agent
  journalctl -u bridge-worker-agent -f
fi
```

从 Bridge 主机检查所有 Worker：

```bash
curl -fsS http://192.168.178.52:8765/v1/health
curl -fsS http://192.168.178.50:8765/v1/health
curl -fsS http://192.168.178.53:8765/v1/health
curl -fsS http://192.168.178.51:8765/v1/health
```

## 6. 创建任务

先写任务 Markdown：

```bash
cat >/tmp/my-task.md <<'EOF'
# Objective
Describe the exact engineering goal.

# Required Changes
- Change A
- Change B

# Acceptance Criteria
- Focused tests pass
- No unrelated changes

# Constraints
- Keep the change scoped
EOF
```

创建：

```bash
bridge create   -p bridge   -t my-task   --task-file /tmp/my-task.md
```

常用时间参数：

```bash
bridge create   -p bridge   -t my-task   --task-file /tmp/my-task.md   --target-minutes 10   --soft-timeout-minutes 12   --timeout-minutes 15
```

## 7. 两种运行模式

### 推荐：长期自治模式

```bash
bridge serve --with-pipeline
```

pipeline 会循环执行：

```text
review
→ auto-dispatch
→ integrate
→ conflict check
```

systemd 安装脚本默认使用这个模式。

### 手动模式

只启动 API/UI：

```bash
bridge serve
```

然后按需：

```bash
bridge auto-dispatch
bridge status
bridge review-pass -t my-task
bridge review-fix -t my-task --fix-file /tmp/fix.md
bridge integrate --task-id my-task
```

单次 pipeline：

```bash
bridge pipeline --once
```

## 8. UI

打开：

```text
http://<bridge-host>:8080
```

页面：

- Overview：Worker/任务总览
- Tasks：任务列表、筛选、删除任务记录
- Task Detail：状态、时间线、outbox、commit/integration 信息
- Thinking：Worker live thinking / retained history

删除语义：

```text
Delete != Cancel
```

运行中的任务被删除时，UI 可以立即移除记录视图，但 Agent / CodeArts 继续执行；Bridge 在安全时机做 deferred cleanup。

## 9. Worker 交付物

Worker 正常完成时需要产生：

```text
RESULT.md
TESTS.md
DIFF.stat
DIFF.patch
```

Agent 的实际流程：

```text
CodeArts
→ projectRoot/.codeartsbridge/outbox/<jobId>
→ Agent archive
→ COMPLETED
→ Bridge fetch
→ task outbox
```

`COMPLETED` 的语义是：Agent archive 已经完成，可以安全 fetch。

## 10. CodeArts 固定版本与 write/edit 当前注意事项

### 10.1 固定版本

当前实验室已验证可用版本：

```text
26.8.12
```

GitHub Release：

```text
codearts-cli-26.8.12-pinned
```

资产：

```text
codearts-install-26.8.12-linux-x64.tar.gz
codearts-install-26.8.12-linux-x64.tar.gz.sha256
```

SHA-256：

```text
5ab25bff375ba0027757d4cb46f46c22b32cc7df9973ca75d2a86ff8aa3a0b67
```

26.9.7 在现有实验室账号上会在 Model Queuing 阶段被 package/account gate 拒绝，因此生产 Worker **禁止 `codearts upgrade`**。完整恢复步骤见 `docs/CODEARTS-PINNED-RUNTIME.md`。

### 10.2 built-in write/edit

26.8.12 的 built-in `write` 已完成受控验证。此前立即拒绝的真实原因是：

1. 修改了未被 CLI 使用的影子 `global.json`；
2. 真实 data path 下的 `edit/write/external_directory_write/dotfile` 仍是 `ask`；
3. 旧 Agent 继承 `OPENCODE_*`，再次指向旧配置。

部署后必须执行：

```bash
python3 deploy/codearts-worker-runtime.py audit \
  --expected-version 26.8.12 \
  --require-aksk
```

需要修复权限时先预览，再显式应用：

```bash
python3 deploy/codearts-worker-runtime.py fix-permissions
python3 deploy/codearts-worker-runtime.py fix-permissions --apply
```

修复工具会先备份真实权限文件，不修改其他权限或凭据。完整调查矩阵、Agent 环境清理、回滚和真实写入验收见 `docs/CODEARTS-WRITE-PERMISSION-RUNBOOK.md`。

shell/python fallback 仍可作为任务级应急路径，但不能代替 built-in write 的部署验收。

### 10.3 built-in write 真实验收

权限 audit 全绿仍只是配置证据。最终必须通过 Agent HTTP Job 或 Bridge 真实 task 验证，并同时满足：

```text
state = COMPLETED
exitCode = 0
事件中存在 tool=write
目标文件内容与要求一致
没有 bash/python/printf/heredoc fallback
```

推荐让任务在 native write 后再用 built-in read 回读文件。完整请求样例、事件证据和验收矩阵见 `docs/CODEARTS-WRITE-PERMISSION-RUNBOOK.md`。

## 11. 升级

这里的“升级”默认只指 **CodeartsBridge 自身**，不包括 CodeArts CLI。

CodeArts CLI 当前固定在 26.8.12，除非完成独立测试与真实任务验收，否则不要升级。

Bridge 主机：

```bash
cd /path/to/CodeartsBridge
git pull --ff-only
./deploy/install-bridge.sh
```

Worker：

```bash
cd /path/to/CodeartsBridge
git pull --ff-only
./deploy/install-worker-agent.sh
```

以上命令适用于由安装脚本管理的系统级 service。当前实验室四台是用户级 service，不要在原 runtime 目录直接 `git pull` 后假设服务已升级。安全升级步骤是：

1. 新建干净 runtime checkout，并固定到准备部署的 commit。
2. 验证 CLI、测试和 `bridge.agent.cli --help`。
3. 备份现有用户 unit，更新其中的 `WorkingDirectory` / `PYTHONPATH`。
4. `systemctl --user daemon-reload && systemctl --user restart bridge-worker-agent`。
5. 运行 runtime audit、四台 health 和一个真实 native write Job。
6. 验证完成前保留旧 runtime，以便把 unit 指回原路径回滚。

## 12. 常见排障

### UI 不是最新

```bash
git rev-parse HEAD
curl -fsS http://127.0.0.1:8080/js/pages/tasks.js | head
sudo systemctl restart bridge
```

### Worker 显示 offline

先在 Worker：

```bash
codearts --version
curl -fsS http://127.0.0.1:8765/v1/health
systemctl --user is-enabled bridge-worker-agent.service || true
systemctl is-enabled bridge-worker-agent.service || true
```

确认 scope 后只查对应日志：

```bash
journalctl --user -u bridge-worker-agent -n 100 --no-pager
# 或系统级：journalctl -u bridge-worker-agent -n 100 --no-pager
```

再从 Bridge 主机：

```bash
curl -fsS http://<worker-ip>:8765/v1/health
```

### 任务 exit 0 但缺成果

检查：

```text
Agent job artifacts
projectRoot/.codeartsbridge/outbox/
Bridge tasks/<taskId>/outbox/
```

不要先改 lifecycle。当前正确顺序必须保持：

```text
drain streams
→ archive outbox
→ set COMPLETED
→ Bridge fetch
```

### 任务看起来删了但 Worker 还在跑

这是预期行为：

```text
Delete != Cancel
```

详见 `docs/ai-closeout/08-TASK-DELETION-SEMANTICS.md`。

## 13. 开发验证

```bash
source .venv/bin/activate
python -m pytest -q
python -m bridge.cli --help
python -m bridge.cli doctor
```

改了真实 Worker 链路后必须再跑一个真实 task。

## 14. 文档入口

- `AGENTS.md` — AI / 新维护者第一入口
- `README.md` — 项目概要与 Quick Start
- `docs/USAGE.md` — 本文，安装和运行手册
- `docs/CODEARTS-PINNED-RUNTIME.md` — CodeArts 26.8.12 固定版本、恢复包、升级规则
- `docs/ai-closeout/NEXT.md` — 当前下一步
- `protocol/WORKER.md` — Worker 执行契约
