# CodeartsBridge 使用与运维手册

> 这是当前运行手册。适用于人类维护者和 Coding Agent。
>
> 快速理解项目先读仓库根目录 `AGENTS.md`。

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
- `codearts --version` 能在运行 Agent 的用户下成功
- 目标项目已经 checkout 到 `projects.json` 里的 `projectRoot`

建议所有机器上的 CodeartsBridge 仓库使用同一路径，当前实验室是：

```text
/home/nathan/bridge-python
```

但代码本身不依赖这个固定路径；安装脚本会以当前仓库路径生成 systemd unit。

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

每台 Worker：

```bash
git clone https://github.com/nathanxiangang-web/CodeartsBridge.git
cd CodeartsBridge

codearts --version
./deploy/install-worker-agent.sh
```

安装脚本会：

1. 创建/更新 `.venv`
2. editable install 当前仓库
3. 创建 Agent data root
4. 创建 `~/.config/codeartsbridge/agent.json`
5. 安装并启动 `bridge-worker-agent.service`
6. 检查 `/v1/health`

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
sudo systemctl status bridge-worker-agent
curl -fsS http://127.0.0.1:8765/v1/health
```

日志：

```bash
journalctl -u bridge-worker-agent -f
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

## 10. CodeArts write/edit 当前注意事项

当前已知：

- permission hang 已经处理过
- `--format json` 下 built-in `write/edit` 仍可能立即拒绝
- Worker contract 允许 shell fallback 写成果
- 当前 fallback 经真实 outbox 任务验证能工作
- built-in write 本身仍应视为一个待进一步确认的 CodeArts CLI 行为

看到 `python3 -c` 写 outbox 不代表 Agent 出错；这是当前 fallback 路径之一。

但正常项目源码如果长期全部退化成 base64 / `python3 -c` 整文件覆盖，应单独审查 Worker contract，而不是把这种行为当成理想编辑方式。

## 11. 升级

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

脚本是幂等的：重新安装 editable package，并重启对应 systemd 服务。

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
journalctl -u bridge-worker-agent -n 100 --no-pager
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
- `docs/ai-closeout/NEXT.md` — 当前下一步
- `protocol/WORKER.md` — Worker 执行契约
