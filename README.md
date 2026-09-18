# CodeartsBridge v0.3

CodeArts Agent 多节点调度桥 — 通过 Web UI 实时监控多台远程 Worker 节点，自动派发任务、回显思考过程、审查输出文件。

> **给 AI 助手的快速理解**：这是一个 Python 服务，运行在主节点上，通过 SSH 将编码任务分发到多台远程 Worker 机器并行执行。Worker 上需安装 CodeArts CLI（华为云 AI 编码助手）。Web UI 实时显示每台 Worker 的思考过程和工具调用。你只需要配置好 SSH 和 workers.json，然后 `bridge serve` 启动服务。

## v0.3 更新

- **实时监控修复** — 修复 data-worker 属性丢失导致 log API 永不调用的根因，轮询每 2 秒自动刷新
- **Cache-Control** — 服务器返回 no-cache 头，浏览器不再缓存旧页面
- **4 窗口固定布局** — 按 Worker 固定 4 个监控窗口（178.50 优先），设备地址永远显示
- **计时器实时跳动** — 思考中状态每秒更新计时，完成停止，重新派发重新计时
- **增量事件渲染** — 新事件带 fade-in 动画渐入，自动滚动到底部
- **完成任务保留** — done 状态任务保留显示不清空，新任务来才替换

## 架构

```
┌─────────────────────────────────┐
│         Web UI (:8080)          │
│  Dashboard / Tasks / Thinking   │
│  Workers / Review / Settings    │
└──────────┬──────────────────────┘
           │ HTTP API
┌──────────┴──────────────────────┐
│        Bridge Server            │
│  dispatch / state / transport   │
└──┬────────┬────────┬───────────┘
   │ SSH    │ SSH    │ SSH
┌──┴──┐  ┌──┴──┐  ┌──┴──┐
│W01  │  │W02  │  │W03  │  ...
│codearts│ │codearts│ │codearts│
└─────┘  └─────┘  └─────┘
```

**工作流程**：
1. 主节点运行 `bridge serve` 启动 HTTP API + Web UI
2. `bridge create` 创建任务（Markdown 文件描述要做什么）
3. `bridge dispatch` 将任务分配给有匹配能力的 Worker
4. `bridge run -t <task-id>` 通过 SSH 在远程 Worker 上执行 CodeArts CLI
5. Worker 上的 `session.log`（JSON Lines 格式）记录推理步骤和工具调用
6. Web UI 每 2 秒轮询 `/api/tasks/<id>/log` 增量渲染事件流

## 快速开始

```bash
# 一键安装
curl -fsSL https://raw.githubusercontent.com/nathanxiangang-web/CodeartsBridge/master/install.sh | bash -s install

# 启动服务
bridge serve --host 0.0.0.0 --port 8080

# 打开浏览器
open http://localhost:8080
```

## 安装

### 前置条件

| 条件 | 说明 |
|------|------|
| Python >= 3.10 | 主节点和 Worker 节点都需要 |
| SSH 免密登录 | 主节点 → 各 Worker 节点，用 `ssh-copy-id user@host` 配置 |
| CodeArts CLI | 各 Worker 节点需安装华为云 CodeArts CLI 并配置 AK/SK |
| 远程工作目录 | 各 Worker 上需有项目代码仓库（git clone 好的） |

**SSH 免密配置**：
```bash
# 在主节点上生成密钥（如果没有）
ssh-keygen -t ed25519 -N "" -f ~/.ssh/id_ed25519

# 分发到各 Worker 节点
ssh-copy-id -i ~/.ssh/id_ed25519.pub nathan@192.168.178.50
ssh-copy-id -i ~/.ssh/id_ed25519.pub nathan@192.168.178.52
# ... 对每台 Worker 重复
```

**CodeArts CLI 安装**（在每台 Worker 上）：
```bash
# 安装 CodeArts CLI（具体方式参考华为云文档）
# 配置 AK/SK
codearts config set-access-key YOUR_AK
codearts config set-secret-key YOUR_SK
```

### 方式一：一键脚本（推荐）

```bash
./install.sh install    # 安装
./install.sh uninstall  # 卸载
./install.sh help       # 使用说明
```

### 方式二：手动安装

```bash
git clone https://github.com/nathanxiangang-web/CodeartsBridge.git
cd CodeartsBridge
pip install -e .
export PYTHONPATH=src  # 如未 pip install，需设置
```

## 配置

两个 JSON 配置文件放在项目根目录（或 `--config-dir` 指定目录）。

### projects.json — 定义项目

每个项目指定一台远程 Worker 机器的 SSH 连接信息和远程路径：

```json
{
  "schemaVersion": 1,
  "projects": [
    {
      "projectId": "codex-glm-ma-w01",
      "transport": "ssh",
      "sshHost": "nathan@192.168.178.52",
      "remoteBridgeRoot": "/home/nathan/.codex-glm-bridge",
      "remoteProjectPath": "/home/nathan/myproject"
    }
  ]
}
```

| 字段 | 说明 |
|------|------|
| `projectId` | 项目唯一标识，workers.json 通过此字段关联 |
| `transport` | 传输方式：`local` / `ssh` / `ssh-shell` / `remote-worktree` |
| `sshHost` | SSH 连接地址 `user@ip` |
| `remoteBridgeRoot` | Worker 上 Bridge 的工作目录（存 session.log、任务状态等） |
| `remoteProjectPath` | Worker 上项目代码仓库路径（CodeArts CLI 在此目录执行） |

### workers.json — 定义工作节点

每个 Worker 绑定一个项目，指定角色和能力：

```json
{
  "schemaVersion": 1,
  "workers": [
    {
      "workerId": "bus-w01-dev",
      "projectId": "codex-glm-ma-w01",
      "role": "implement",
      "host": "192.168.178.52",
      "capabilities": ["implement", "review", "test"]
    }
  ]
}
```

| 字段 | 说明 |
|------|------|
| `workerId` | Worker 唯一标识 |
| `projectId` | 关联的 projectId（指向 projects.json） |
| `role` | 角色：`implement`（开发）/ `review`（审查）/ `test`（测试） |
| `host` | Worker IP 地址（用于 Web UI 显示） |
| `capabilities` | 该 Worker 支持的能力列表，任务会分配到有匹配能力的 Worker |

## 使用

### 完整流程：创建 → 派发 → 运行 → 查看

```bash
# 1. 写任务文件（Markdown 格式，描述要做什么）
cat > my-task.md << 'EOF'
读取 WORKER.md 文件内容并总结其要点，列出所有章节标题
EOF

# 2. 创建任务（指定项目和 Worker）
bridge create -p codex-glm-ma-w01 -w bus-w01-dev -t task-001 -f my-task.md

# 3. 派发任务（将 QUEUED 任务分配给 Worker）
bridge dispatch --max-workers 4

# 4. 运行任务（通过 SSH 在远程 Worker 执行 CodeArts CLI）
bridge run -t task-001

# 5. 查看所有任务状态
bridge status

# 6. 启动 Web UI 服务
bridge serve --host 0.0.0.0 --port 8080
```

### 任务文件格式

任务文件是普通 Markdown 文件，内容就是给 CodeArts CLI 的指令：

```markdown
读取 src/main.py 文件，找到所有 TODO 注释，列出每个 TODO 的位置和内容。
```

```markdown
修复 src/api/handler.py 中的空指针异常，添加 null 检查。
写测试用例验证修复。
```

### CLI 命令一览

| 命令 | 说明 |
|------|------|
| `bridge create -p <项目> -w <Worker> -t <任务ID> -f <文件>` | 创建任务 |
| `bridge dispatch [--max-workers N]` | 派发所有 QUEUED 任务 |
| `bridge run -t <任务ID>` | 执行单个任务（SSH 到 Worker 跑 CodeArts） |
| `bridge status` | 查看所有任务状态 |
| `bridge serve --host 0.0.0.0 --port 8080` | 启动 Web UI + HTTP API |
| `bridge cancel -t <任务ID>` | 取消任务 |

**停止服务**：`Ctrl+C` 或 `kill $(pgrep -f "bridge.*serve")`

## HTTP API

Web UI 依赖的 API 端点（也可供外部集成）：

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/tasks` | 列出所有任务 |
| GET | `/api/tasks/<id>` | 获取单个任务详情（含 meta.workerId） |
| GET | `/api/tasks/<id>/log` | 获取任务日志（事件流、计时、工具计数） |
| POST | `/api/tasks/<id>/cancel` | 取消任务 |
| GET | `/api/workers` | 列出所有 Worker 节点 |
| GET | `/api/projects` | 列出所有项目 |
| GET | `/api/health` | 健康检查 |

**`/api/tasks/<id>/log` 返回格式**：
```json
{
  "startTime": 1789721966071,
  "elapsed": 45,
  "events": [
    {"type": "step_start", "timestamp": "...", "part": "..."},
    {"type": "reasoning", "timestamp": "...", "part": "分析文件结构..."},
    {"type": "tool_use", "timestamp": "...", "part": "read WORKER.md"}
  ],
  "toolCount": 4,
  "reasoningCount": 3
}
```

## Web UI

浏览器打开 `http://<服务器IP>:8080`，6 个页面：

| 页面 | URL hash | 功能 |
|------|----------|------|
| 仪表盘 | `#dashboard` | 任务/节点/项目总览 |
| 任务 | `#tasks` | 全部任务列表，支持创建 |
| 思考回显 | `#thinking` | 2×2 监控布局，实时显示 Agent 思考流 |
| 工作节点 | `#workers` | 节点在线状态和能力 |
| 审查 | `#review` | 查看已完成任务的输出文件 |
| 设置 | `#settings` | Bridge 配置和健康检查 |

### 思考回显窗口

每个窗口固定对应一台 Worker，实时显示：
- **头部**：设备地址 + 状态徽章 + 计时器（每秒跳动）+ 思考/工具计数 + 任务ID
- **内容**：Agent 实际输出的事件流（2 秒轮询增量渲染）
  - ▶️ 开始执行
  - 💭 推理文本（CodeArts reasoning）
  - 🔧 工具调用（read/write/bash/edit + 文件名）
- **动画**：新事件 fade-in 渐入，自动滚动到底部

**三种状态映射**：
- 排队 = CREATED / QUEUED / READY / STARTING
- 思考中 = RUNNING / ASSISTANCE_REQUIRED / INTEGRATING
- 完成 = DONE / REVIEW_REQUIRED / REVIEW_PASSED / CANCELLED / FAILED 等

## Transport 类型

| transport | CLI 位置 | 适用场景 |
|-----------|---------|---------|
| `local` | 本机 | 本地开发调试 |
| `ssh` | 远端 | 生产多节点（推荐） |
| `ssh-shell` | 本机 | 远端无 CLI 降级 |
| `remote-worktree` | 远端 | 独立仓库并行开发 |

## 项目结构

```
src/bridge/
├── api/server.py        # HTTP API + Web UI
├── cli.py               # CLI 入口
├── dispatch.py          # 任务调度
├── state.py             # 状态机
├── worker.py            # Worker 执行
├── transport/
│   ├── ssh.py           # SSH transport
│   ├── local.py         # 本地 transport
│   └── remote_worktree.py
├── runtime/
│   ├── heartbeat.py     # 心跳追踪
│   └── supervisor.py    # 运行时监控
└── web/index.html       # Web UI 单页应用
```

## 开发

```bash
pip install -e ".[dev]"   # 安装开发依赖
pytest                    # 运行测试
export PYTHONPATH=src     # 设置 Python 路径
```

## License

MIT
