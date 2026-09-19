# CodeartsBridge

面向多 AI 软件开发的轻量级任务控制平面 — 将编码任务分发到多台 Worker 节点并行执行，实时监控 Agent 思考过程，自动审查与集成。

> **给 AI 助手的快速理解**：这是一个 Python 服务，运行在主节点上。你配置好 `projects.json`（项目）和 `workers.json`（工作节点），然后 `bridge serve` 启动服务。任务通过 CLI 或 Web UI 创建，自动派发到有匹配能力的 Worker。Worker 上的 CodeArts CLI（华为云 AI 编码助手）执行任务，事件流实时回传。Web UI 提供 10 个页面的控制中心。支持两种 transport：SSH（直接远程执行）和 Agent（HTTP API 常驻进程，推荐）。

## 架构

```
┌──────────────────────────────────────────────┐
│            Control Center UI (:8080)          │
│  Dashboard / Projects / Tasks / DAG / Workers │
│  Review / Thinking / Metrics / Settings       │
└──────────────────┬───────────────────────────┘
                   │ HTTP API + SSE
┌──────────────────┴───────────────────────────┐
│                 Bridge Server                 │
│  dispatch / state / transport / supervision   │
│  EventStore (flock + rotation) / SSE cursor   │
└──┬──────────┬──────────┬──────────┬─────────┘
   │ Agent    │ Agent    │ Agent    │ Agent
┌──┴──┐    ┌──┴──┐    ┌──┴──┐    ┌──┴──┐
│W01  │    │W02  │    │W03  │    │W04  │
│:8765│    │:8765│    │:8765│    │:8765│
│codearts│ │codearts│ │codearts│ │codearts│
└─────┘    └─────┘    └─────┘    └─────┘
```

**核心组件**：

| 组件 | 说明 |
|------|------|
| **Bridge Server** | 主节点 HTTP API + Web UI，任务调度与状态管理 |
| **Agent Server** | Worker 节点常驻进程（:8765），接收任务、执行 CodeArts CLI、回传事件 |
| **EventStore** | 事件存储，fcntl.flock 并发安全，10MB 自动轮转 |
| **Supervision** | 事件驱动架构师：DeadlineScheduler + Supervisor + TaskInspector + ArchitectReactor |
| **Control Center UI** | 10 页面模块化前端，SSE 实时推送，Playwright E2E 测试 |

**工作流程**：
1. `bridge serve` 启动 HTTP API + Web UI（主节点）
2. 每台 Worker 运行 `bridge-worker-agent`（常驻进程 :8765）
3. `bridge create` 创建任务（Markdown 文件描述要做什么）
4. `bridge dispatch` 将任务分配给有匹配能力的 Worker
5. Bridge 通过 Agent transport（HTTP API）将任务发送到 Worker
6. Worker 上的 Agent Server 调用 CodeArts CLI 执行任务
7. 事件流（reasoning、tool_use、step）实时回传到 Bridge
8. Web UI 通过 SSE 实时渲染思考过程
9. `bridge integrate` 将 DONE 任务集成到主分支

## 快速开始

### 一键安装

```bash
curl -fsSL https://raw.githubusercontent.com/nathanxiangang-web/CodeartsBridge/main/install.sh | bash -s install
```

### 手动安装

```bash
git clone https://github.com/nathanxiangang-web/CodeartsBridge.git
cd CodeartsBridge
pip install -e .
```

### 启动服务

```bash
# 1. 主节点：启动 Bridge Server（HTTP API + Web UI）
bridge serve --host 0.0.0.0 --port 8080

# 2. 每台 Worker：启动 Agent Server
bridge-worker-agent --listen 0.0.0.0 --port 8765

# 3. 打开浏览器
open http://<主节点IP>:8080
```

## 前置条件

| 条件 | 说明 |
|------|------|
| Python >= 3.10 | 主节点和 Worker 节点都需要 |
| CodeArts CLI | 各 Worker 节点需安装华为云 CodeArts CLI 并配置 AK/SK |
| SSH 免密登录 | 仅 SSH transport 模式需要（Agent transport 不需要） |

**CodeArts CLI 安装**（在每台 Worker 上）：
```bash
# 安装 CodeArts CLI（参考华为云文档）
# 配置 AK/SK
codearts config set-access-key YOUR_AK
codearts config set-secret-key YOUR_SK
```

## 配置

两个 JSON 配置文件放在项目根目录（或 `--config-dir` 指定目录）。

### projects.json — 定义项目

```json
{
  "schemaVersion": 1,
  "defaults": {
    "runMode": "auto",
    "model": "huaweicloud-maas/GLM-5.2",
    "timeoutMinutes": 60
  },
  "projects": [
    {
      "id": "my-project",
      "transport": "local",
      "projectRoot": "/home/user/myproject",
      "runMode": "auto",
      "model": "huaweicloud-maas/GLM-5.2",
      "timeoutMinutes": 60
    },
    {
      "id": "my-project-remote",
      "transport": "ssh",
      "projectRoot": "/home/user/myproject",
      "sshHost": "user@192.168.1.100",
      "remoteBridgeRoot": "/home/user/.bridge",
      "remoteCliPath": "codearts",
      "runMode": "auto",
      "timeoutMinutes": 60
    }
  ]
}
```

| 字段 | 说明 |
|------|------|
| `id` | 项目唯一标识 |
| `transport` | `local` / `ssh` / `ssh-shell` / `remote-worktree` / `agent` |
| `projectRoot` | 项目代码仓库路径 |
| `sshHost` | SSH 连接地址（SSH 模式） |
| `remoteBridgeRoot` | Worker 上 Bridge 工作目录 |
| `remoteCliPath` | CodeArts CLI 路径 |
| `model` | 使用的模型 |
| `timeoutMinutes` | 任务超时时间 |

### workers.json — 定义工作节点

```json
{
  "schemaVersion": 1,
  "defaults": {
    "model": "huaweicloud-maas/GLM-5.2",
    "concurrencyLimit": 1,
    "enabled": true
  },
  "workers": [
    {
      "id": "worker-01",
      "transport": "agent",
      "host": "user@192.168.1.100",
      "endpoint": "http://192.168.1.100:8765",
      "agentTokenEnv": "BRIDGE_AGENT_W01_TOKEN",
      "cliPath": "/home/user/.codeartsdoer/installers/bin/codearts",
      "model": "huaweicloud-maas/GLM-5.2",
      "concurrencyLimit": 1,
      "enabled": true,
      "capabilities": ["implement", "review", "test"]
    }
  ]
}
```

| 字段 | 说明 |
|------|------|
| `id` | Worker 唯一标识 |
| `transport` | `agent`（推荐）/ `ssh` / `local` |
| `endpoint` | Agent Server 地址（agent transport） |
| `agentTokenEnv` | Agent 认证 token 的环境变量名 |
| `cliPath` | Worker 上 CodeArts CLI 路径 |
| `capabilities` | 该 Worker 支持的能力列表 |
| `concurrencyLimit` | 并发任务上限 |

### supervision.json — 监督配置（可选）

```json
{
  "deadlineSeconds": 3600,
  "inspectIntervalSeconds": 300,
  "hardCollectDelaySeconds": 15,
  "cleanupDelaySeconds": 16,
  "capacityCooldownSeconds": 60,
  "reviewLockTtlSeconds": 1800
}
```

## Transport 类型

| transport | 通信方式 | 适用场景 |
|-----------|---------|---------|
| `agent` | HTTP API（:8765） | **生产推荐** — 常驻进程，无需 SSH |
| `ssh` | SSH 远程执行 | 传统多节点 |
| `local` | 本地进程 | 开发调试 |
| `ssh-shell` | SSH shell 降级 | 远端无 CLI |
| `remote-worktree` | SSH + 独立 worktree | 并行开发隔离 |

**Agent transport 优势**：无需 SSH 免密配置、常驻进程启动快、事件流实时回传、支持 inflight 恢复。

## CLI 命令

| 命令 | 说明 |
|------|------|
| `bridge bootstrap` | 初始化 Bridge 目录结构 |
| `bridge doctor` | 检查环境和配置 |
| `bridge status` | 查看所有项目和任务状态 |
| `bridge create -p <项目> -w <Worker> -t <任务ID> -f <文件>` | 创建任务 |
| `bridge dispatch [--max-workers N]` | 派发任务到 Worker |
| `bridge auto-dispatch` | 自动派发就绪任务 |
| `bridge run -t <任务ID>` | 执行单个任务 |
| `bridge review-pass -t <任务ID>` | 标记任务审查通过 |
| `bridge review-fix -t <任务ID> --fix-file <文件>` | 请求修复任务 |
| `bridge cancel -t <任务ID>` | 取消任务 |
| `bridge pause` | 暂停派发 |
| `bridge resume` | 恢复派发 |
| `bridge serve --host 0.0.0.0 --port 8080` | 启动 Web UI + HTTP API |
| `bridge pipeline [--interval N] [--max-workers N]` | 运行完整流水线 |
| `bridge integrate` | 集成 DONE 任务到主分支 |
| `bridge projects` | 列出已注册项目 |
| `bridge workers` | 列出已注册 Worker |
| `bridge telemetry` | 显示遥测统计 |
| `bridge adaptive-dispatch` | 自适应派发（遥测调参） |
| `bridge cost [--project <ID>]` | 显示成本报告 |

**Worker Agent 命令**：
```bash
bridge-worker-agent --listen 0.0.0.0 --port 8765 --root ~/.bridge/agent
```

## 任务文件格式

任务文件是普通 Markdown，内容即给 CodeArts CLI 的指令：

```markdown
读取 src/main.py 文件，找到所有 TODO 注释，列出每个 TODO 的位置和内容。
```

```markdown
修复 src/api/handler.py 中的空指针异常，添加 null 检查。
写测试用例验证修复。
```

## 完整流程示例

```bash
# 1. 写任务文件
cat > my-task.md << 'EOF'
读取 WORKER.md 文件内容并总结其要点，列出所有章节标题
EOF

# 2. 创建任务
bridge create -p my-project -w worker-01 -t task-001 -f my-task.md

# 3. 派发任务
bridge dispatch --max-workers 4

# 4. 查看状态
bridge status

# 5. 启动 Web UI（如果尚未启动）
bridge serve --host 0.0.0.0 --port 8080

# 6. 浏览器打开 http://<IP>:8080 查看实时执行

# 7. 任务完成后集成
bridge integrate
```

## Web UI

浏览器打开 `http://<服务器IP>:8080`，10 个页面：

| 页面 | URL hash | 功能 |
|------|----------|------|
| 仪表盘 | `#dashboard` | 在线/空闲/禁用 Worker 统计，运行/审查/失败任务计数 |
| 项目 | `#projects` | 项目列表，逻辑分组（项目 > Profile） |
| 任务 | `#tasks` | 全部任务列表，状态过滤、搜索、创建 |
| 工作节点 | `#workers` | Worker 卡片：在线状态、当前任务、心跳、能力 |
| 审查 | `#review` | 已完成任务审查：目标、验收标准、变更文件 |
| 指标 | `#metrics` | 遥测指标和统计 |
| 思考回显 | `#thinking` | 实时显示 Agent 思考流（SSE 推送） |
| 设置 | `#settings` | Bridge 配置和健康检查 |

**技术栈**：浏览器原生 ES Modules（无构建工具、无前端框架），CSS 模块化（tokens/base/layout/components/pages），SSE 实时事件推送 + 轮询降级。

## HTTP API

### Bridge Server API

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/health` | 健康检查 |
| GET | `/api/tasks` | 列出所有任务 |
| GET | `/api/tasks/<id>` | 获取任务详情 |
| GET | `/api/tasks/<id>/log` | 获取任务日志（事件流） |
| POST | `/api/tasks/<id>/cancel` | 取消任务 |
| GET | `/api/workers` | 列出所有 Worker |
| GET | `/api/projects` | 列出所有项目 |
| GET | `/api/events/stream` | SSE 事件流（实时推送） |

### Agent Server API（Worker :8765）

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/v1/health` | Agent 健康检查 |
| POST | `/v1/jobs` | 创建并启动任务 |
| GET | `/v1/jobs/<id>` | 查询任务状态 |
| GET | `/v1/jobs/<id>/events?cursor=N` | 事件流（增量游标） |
| POST | `/v1/jobs/<id>/cancel` | 取消任务 |
| GET | `/v1/jobs/<id>/artifacts` | 列出产出文件 |
| GET | `/v1/jobs/<id>/files/<category>/<name>` | 下载原始文件 |

## Supervision 子系统

事件驱动架构师模块（`src/bridge/supervision/`）：

| 模块 | 功能 |
|------|------|
| `schedule.py` | DeadlineScheduler — 截止时间监控 |
| `supervisor.py` | Supervisor — 任务监督，hard_collect (T+15)、cleanup (T+16) |
| `inspector.py` | TaskInspector — 任务检查与诊断 |
| `queue.py` | ArchitectQueue — 架构师任务队列 |
| `reactor.py` | ArchitectReactor — 事件反应器 |
| `flags.py` | FeatureFlags — 一行回滚的功能开关 |
| `background.py` | BackgroundScheduler — 后台调度 |
| `capacity.py` | CapacityMonitor — 容量监控（带冷却） |
| `review_lock.py` | ReviewLock — 文件审查锁（TTL） |
| `recovery.py` | Recovery — 故障恢复策略 |

## 项目结构

```
src/bridge/
├── cli.py                    # CLI 入口（20 个命令）
├── daemon.py                 # 守护进程
├── dispatch.py               # 任务调度
├── state.py                  # 状态机（带 revision 字段）
├── task.py                   # 任务管理
├── worker.py                 # Worker 执行
├── auto_dispatch.py          # 自动派发
├── pipeline.py               # 完整流水线
├── integration.py            # 任务集成
├── cost.py                   # 成本追踪
├── codearts.py               # CodeArts CLI 封装
├── config.py                 # 配置加载
├── atomic.py                 # 原子写入
├── locks.py                  # 文件锁
├── agent/                    # Agent Server（Worker 端）
│   ├── cli.py                # Agent CLI 入口
│   ├── server.py             # HTTP Server (:8765)
│   ├── runner.py             # 任务执行器
│   ├── watchdog.py           # 进程看门狗
│   ├── auth.py               # Token 认证
│   ├── artifacts.py          # 产出文件管理
│   ├── fs_guard.py           # 文件系统安全
│   ├── recovery.py           # inflight 恢复
│   └── store.py              # 状态存储
├── supervision/              # 事件驱动架构师
│   ├── model.py              # 事件模型
│   ├── schedule.py           # 截止时间调度
│   ├── supervisor.py         # 任务监督
│   ├── inspector.py          # 任务检查
│   ├── queue.py              # 架构师队列
│   ├── reactor.py            # 事件反应器
│   ├── policy.py             # 策略引擎
│   ├── recovery.py           # 恢复策略
│   ├── config.py             # 监督配置
│   ├── flags.py              # 功能开关
│   ├── background.py         # 后台调度
│   ├── capacity.py           # 容量监控
│   └── review_lock.py        # 审查锁
├── transport/                # 传输层
│   ├── agent.py              # Agent transport（HTTP API）
│   ├── ssh.py                # SSH transport
│   ├── local.py              # 本地 transport
│   ├── ssh_shell.py          # SSH shell 降级
│   └── remote_worktree.py    # 远程 worktree
├── core/                     # 核心领域
│   ├── events.py             # EventStore（flock + rotation）
│   ├── state.py              # 状态机（带 revision）
│   └── models.py             # 领域模型
├── runtime/                  # 运行时
│   ├── supervisor.py         # 运行时监控（re-attach + orphan 收敛）
│   ├── heartbeat.py          # 心跳追踪
│   ├── process.py            # 进程管理
│   ├── cancellation.py       # 取消处理
│   ├── recovery.py           # 恢复处理
│   └── timeout.py            # 超时处理
├── scheduler/                # 调度器
│   ├── affinity.py           # 主机亲和性
│   ├── capacity.py           # 容量管理
│   ├── dependency.py         # 依赖解析
│   ├── lease.py              # 租约管理
│   └── matcher.py            # 能力匹配
├── api/server.py             # HTTP API Server
├── application/              # 应用服务层
├── policy/                   # 策略引擎
└── web/                      # Control Center UI
    ├── index.html            # 54 行 app shell
    ├── styles/               # CSS 模块化
    │   ├── tokens.css        # 设计令牌
    │   ├── base.css          # 基础样式（含中文字体）
    │   ├── layout.css        # 布局
    │   ├── components.css    # 组件
    │   └── pages.css         # 页面
    └── js/
        ├── api.js            # API 客户端
        ├── app.js            # 应用入口
        ├── events.js         # SSE 事件核心
        ├── i18n.js           # 国际化
        ├── utils.js          # 工具函数
        ├── components/       # UI 组件（7 个）
        └── pages/            # 页面模块（10 个）
```

## 部署

### systemd 服务

**Bridge Server**（主节点）：
```bash
sudo cp deploy/bridge-daemon.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable bridge-daemon
sudo systemctl start bridge-daemon
```

**Worker Agent**（每台 Worker）：
```bash
sudo cp deploy/bridge-worker-agent.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable bridge-worker-agent
sudo systemctl start bridge-worker-agent
```

### Worker Agent 安装

```bash
# 在每台 Worker 上运行
./deploy/install-worker-agent.sh
```

这会：
1. 创建 `~/.codex-glm-bridge/agent` 数据目录
2. 生成 Agent 认证 token
3. 安装 systemd 服务

## 开发

```bash
pip install -e ".[dev]"   # 安装开发依赖
pytest                    # 运行测试（855 个）
pytest tests/supervision/ # 监督子系统测试
pytest tests/ui/          # Playwright E2E 测试
export PYTHONPATH=src     # 如未 pip install
```

**测试覆盖**：
- 855 个单元测试
- 13 个 Playwright 浏览器 E2E 测试
- 109 个 supervision 子系统测试

## 开发文档

- `docs/Bridge-Worker-Runtime-开发文档.md` — Worker Runtime 基础性重写
- `docs/CodeartsBridge-事件驱动架构师与5-3-3-2-2-1巡检-开发文档.md` — 事件驱动架构师调度与巡检
- `docs/开发文档.md` — Control Center 1.0 UI 开发

## License

MIT
