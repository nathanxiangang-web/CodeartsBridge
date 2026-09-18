# CodeartsBridge v0.3

CodeArts Agent 多节点调度桥 — 通过 Web UI 实时监控多台远程 Worker 节点，自动派发任务、回显思考过程、审查输出文件。

## v0.3 更新

- **实时监控修复** — 修复 data-worker 属性丢失导致 log API 永不调用的根因，轮询每 2 秒自动刷新
- **Cache-Control** — 服务器返回 no-cache 头，浏览器不再缓存旧页面
- **4 窗口固定布局** — 按 Worker 固定 4 个监控窗口（178.50 优先），设备地址永远显示
- **计时器实时跳动** — 思考中状态每秒更新计时，完成停止，重新派发重新计时
- **增量事件渲染** — 新事件带 fade-in 动画渐入，自动滚动到底部
- **完成任务保留** — done 状态任务保留显示不清空，新任务来才替换

## 功能

- **Web UI 监控** — 仪表盘、任务列表、工作节点、思考回显、审查、设置 6 个页面
- **多节点调度** — 支持 4+ 台远程 Worker 并行执行，SSH transport 自动分发
- **实时思考回显** — 2 秒轮询增量渲染 Agent 推理步骤(💭)和工具调用(🔧)，无需手动刷新
- **三种状态** — 排队 / 思考中 / 完成，mapState 映射所有后端状态
- **i18n 双语** — 中英文一键切换
- **输出审查** — 查看任务 outbox 中的生成文件（DIFF.patch、RESULT.md、TESTS.md 等）
- **计时器** — 基于 session.log 实际时间戳计算任务耗时，非页面加载时间

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

### 方式一：一键脚本（推荐）

```bash
# 安装
./install.sh install

# 卸载
./install.sh uninstall

# 使用说明
./install.sh help
```

### 方式二：手动安装

```bash
git clone https://github.com/nathanxiangang-web/CodeartsBridge.git
cd CodeartsBridge
pip install -e .
```

### 前置条件

- Python >= 3.10
- SSH 免密登录到各 Worker 节点
- 远端已安装 CodeArts CLI 并配置 AK/SK

## 配置

### projects.json

定义项目，指定 transport 类型和 SSH 连接信息：

```json
{
  "schemaVersion": 1,
  "projects": [
    {
      "projectId": "my-project",
      "transport": "ssh",
      "sshHost": "user@192.168.1.50",
      "remoteBridgeRoot": "/home/user/.codex-glm-bridge",
      "remoteProjectPath": "/home/user/myproject"
    }
  ]
}
```

### workers.json

定义工作节点，绑定项目和角色：

```json
{
  "schemaVersion": 1,
  "workers": [
    {
      "workerId": "worker-01",
      "projectId": "my-project",
      "role": "implement",
      "host": "192.168.1.50"
    }
  ]
}
```

## 使用

### CLI 命令

```bash
# 创建任务
bridge create -p my-project -w worker-01 -t task-001 -f task-file.md

# 派发任务
bridge dispatch

# 运行任务
bridge run -t task-001

# 查看状态
bridge status

# 启动 Web 服务
bridge serve --host 0.0.0.0 --port 8080
```

### Web UI 页面

| 页面 | 功能 |
|------|------|
| 仪表盘 | 任务/节点/项目总览 |
| 任务 | 全部任务列表，支持创建 |
| 思考回显 | 2×2 监控布局，实时显示 Agent 思考流 |
| 工作节点 | 节点在线状态和能力 |
| 审查 | 查看已完成任务的输出文件 |
| 设置 | Bridge 配置和健康检查 |

### 思考回显窗口

每个窗口固定对应一台 Worker，实时显示：
- **头部**：设备地址 + 状态徽章 + 计时器（每秒跳动）+ 思考/工具计数 + 任务ID
- **内容**：Agent 实际输出的事件流（2 秒轮询增量渲染）
  - ▶️ 开始执行
  - 💭 推理文本（codearts reasoning）
  - 🔧 工具调用（read/write/bash/edit + 文件名）
- **动画**：新事件 fade-in 渐入，自动滚动到底部

## Transport 类型

| transport | CLI 位置 | 适用场景 |
|-----------|---------|---------|
| `local` | 本机 | 本地开发 |
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
# 安装开发依赖
pip install -e ".[dev]"

# 运行测试
pytest

# 设置 Python 路径
export PYTHONPATH=src
```

## License

MIT