# CodeartsBridge 部署与使用指南

> **目标**：拿到本文档 + GitHub 仓库链接 + Worker 机器 IP/密码，即可部署桥并开始使用。

## 1. 这是什么

CodeartsBridge 是一个 **AI 任务调度桥**，让架构者（Architect）创建工程任务，自动派发给远端 Worker（运行 CodeArts CLI 的 GLM 模型），收集结果并审查集成。

```
Architect ──创建任务──▶ Bridge ──派发──▶ Worker (CodeArts CLI / GLM)
         ◀──审查结果──         ◀──交付──
```

- **零第三方依赖** — 纯 Python 3.10+ 标准库
- **Linux 原生** — systemd 服务，无 PowerShell
- **多 Worker 并行** — 支持多台远端机器同时执行
- **自动流水线** — plan → dispatch → review → integrate 全自动

## 2. 前置条件

### 桥机器（运行 Bridge 的机器）

| 依赖 | 版本 | 检查命令 |
|------|------|---------|
| Python | >= 3.10 | `python3 --version` |
| git | 任意 | `git --version` |
| sshpass | 任意（可选，用密码配免密时需要） | `which sshpass` |

### Worker 机器（执行任务的远端机器）

| 依赖 | 说明 |
|------|------|
| CodeArts CLI | `codearts` 命令可用，已配置 AK/SK |
| Python | >= 3.10（部分任务需要） |
| git | 任务涉及 git 操作时需要 |
| SSH | 桥机器能 SSH 到 Worker |

## 3. 快速部署（一键脚本）

### 方式 A：参数式

```bash
# 1. 下载部署脚本
curl -fsSL https://raw.githubusercontent.com/nathanxiangang-web/CodeartsBridge/main/deploy.sh -o deploy.sh
chmod +x deploy.sh

# 2. 执行部署（指定 Worker IP 和密码）
./deploy.sh \
  --workers "192.168.1.51,192.168.1.52" \
  --user nathan \
  --password <你的密码>
```

脚本会自动完成：
1. 克隆仓库到 `~/bridge-python`
2. 安装 Python 依赖
3. 配置 SSH 免密登录到所有 Worker
4. 生成 `workers.json` 和 `projects.json`
5. 运行 `doctor` 环境检查
6. 安装并启动 systemd 服务（root 时）

### 方式 B：环境变量式

```bash
export WORKER_IPS="192.168.1.51,192.168.1.52"
export WORKER_USER=nathan
export WORKER_PASS=<密码>
./deploy.sh
```

### 方式 C：交互式（已有 SSH 免密）

```bash
git clone https://github.com/nathanxiangang-web/CodeartsBridge.git
cd CodeartsBridge
./deploy.sh
# 然后手动编辑 workers.json 和 projects.json
```

## 4. 手动部署（逐步）

### 4.1 克隆仓库

```bash
git clone https://github.com/nathanxiangang-web/CodeartsBridge.git
cd CodeartsBridge
export PYTHONPATH=src
```

### 4.2 安装依赖

```bash
pip3 install -e .
# 或不安装，直接用 PYTHONPATH=src
```

### 4.3 配置 SSH 免密登录

```bash
# 生成密钥（如果没有）
[ ! -f ~/.ssh/id_rsa ] && ssh-keygen -t rsa -b 2048 -f ~/.ssh/id_rsa -N ""

# 配置免密到每个 Worker
ssh-copy-id nathan@192.168.1.51
ssh-copy-id nathan@192.168.1.52

# 验证
ssh nathan@192.168.1.51 "echo ok"
```

### 4.4 初始化

```bash
python3 -m bridge.cli bootstrap
python3 -m bridge.cli doctor
```

### 4.5 配置 workers.json

编辑 `workers.json`，列出所有 Worker 节点：

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
      "transport": "ssh",
      "host": "nathan@192.168.1.51",
      "cliPath": "codearts",
      "model": "huaweicloud-maas/GLM-5.2",
      "concurrencyLimit": 1,
      "enabled": true,
      "capabilities": ["implement", "review", "test"]
    },
    {
      "id": "worker-02",
      "transport": "ssh",
      "host": "nathan@192.168.1.52",
      "cliPath": "codearts",
      "model": "huaweicloud-maas/GLM-5.2",
      "concurrencyLimit": 1,
      "enabled": true,
      "capabilities": ["implement", "review", "test"]
    }
  ]
}
```

**字段说明**：

| 字段 | 必填 | 说明 |
|------|------|------|
| `id` | 是 | Worker 唯一标识 |
| `transport` | 是 | 传输方式：`ssh` / `local` |
| `host` | 是 | SSH 目标 `user@ip` |
| `cliPath` | 是 | Worker 上 `codearts` 命令路径 |
| `model` | 否 | 模型 ID，默认 `huaweicloud-maas/GLM-5.2` |
| `concurrencyLimit` | 否 | 并发任务数，默认 1 |
| `enabled` | 否 | 是否启用，默认 true |
| `capabilities` | 否 | 能力标签：`implement` / `review` / `test` |

### 4.6 配置 projects.json

编辑 `projects.json`，定义项目（每个 Worker 对应一个项目入口）：

```json
{
  "schemaVersion": 1,
  "defaults": {
    "runMode": "auto",
    "model": "huaweicloud-maas/GLM-5.2",
    "timeoutMinutes": 30
  },
  "projects": [
    {
      "id": "my-project-w01",
      "transport": "ssh",
      "projectRoot": "/home/nathan/my-project",
      "runMode": "auto",
      "model": "huaweicloud-maas/GLM-5.2",
      "timeoutMinutes": 30,
      "sshHost": "nathan@192.168.1.51",
      "remoteBridgeRoot": "/home/nathan/my-project",
      "remoteCliPath": "codearts"
    },
    {
      "id": "my-project-w02",
      "transport": "ssh",
      "projectRoot": "/home/nathan/my-project",
      "runMode": "auto",
      "model": "huaweicloud-maas/GLM-5.2",
      "timeoutMinutes": 30,
      "sshHost": "nathan@192.168.1.52",
      "remoteBridgeRoot": "/home/nathan/my-project",
      "remoteCliPath": "codearts"
    }
  ]
}
```

**字段说明**：

| 字段 | 必填 | 说明 |
|------|------|------|
| `id` | 是 | 项目唯一标识 |
| `transport` | 是 | `ssh`（远端执行）/ `local`（本地执行） |
| `projectRoot` | 是 | 项目根目录（Worker 上的路径） |
| `sshHost` | transport=ssh 时 | `user@ip` |
| `remoteBridgeRoot` | 否 | Worker 上桥工作目录 |
| `remoteCliPath` | 否 | Worker 上 `codearts` 路径 |
| `timeoutMinutes` | 否 | 任务超时分钟数 |

### 4.7 验证

```bash
python3 -m bridge.cli doctor    # 环境检查
python3 -m bridge.cli workers   # 列出 Worker
python3 -m bridge.cli projects  # 列出项目
```

### 4.8 启动服务

**方式 1：systemd（推荐）**

```bash
sudo cat > /etc/systemd/system/bridge.service << 'EOF'
[Unit]
Description=CodeartsBridge Service
After=network.target

[Service]
Type=simple
User=nathan
WorkingDirectory=/home/nathan/bridge-python
Environment=PYTHONPATH=/home/nathan/bridge-python/src
ExecStart=/usr/bin/python3 -m bridge.cli serve --host 0.0.0.0 --port 8080
Restart=on-failure
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF

sudo systemctl daemon-reload
sudo systemctl enable --now bridge
```

**方式 2：前台运行**

```bash
PYTHONPATH=src python3 -m bridge.cli serve --host 0.0.0.0 --port 8080
```

## 5. CLI 命令参考

> 以下命令均假设 `PYTHONPATH=src` 已设置，或已 `pip install -e .`

### 5.1 基础命令

| 命令 | 说明 | 示例 |
|------|------|------|
| `bootstrap` | 初始化目录结构 | `bridge bootstrap` |
| `doctor` | 环境检查 | `bridge doctor` |
| `status` | 查看所有任务状态 | `bridge status` |
| `projects` | 列出项目 | `bridge projects` |
| `workers` | 列出 Worker | `bridge workers` |

### 5.2 任务管理

| 命令 | 说明 | 示例 |
|------|------|------|
| `create` | 创建任务 | `bridge create -p my-project -t task-001 --task-file task.md` |
| `dispatch` | 派发任务 | `bridge dispatch` |
| `auto-dispatch` | 自动派发 | `bridge auto-dispatch --loop --interval 10` |
| `run` | 执行单个任务 | `bridge run -t task-001` |
| `cancel` | 取消任务 | `bridge cancel -t task-001` |
| `pause` | 暂停派发 | `bridge pause` |
| `resume` | 恢复派发 | `bridge resume` |

### 5.3 审查与集成

| 命令 | 说明 | 示例 |
|------|------|------|
| `review-pass` | 审查通过 | `bridge review-pass -t task-001` |
| `review-fix` | 审查退回修复 | `bridge review-fix -t task-001 --task-file fix.md` |
| `integrate` | 集成 DONE 任务 | `bridge integrate` |
| `integrate --loop` | 持续集成 | `bridge integrate --loop` |

### 5.4 流水线

| 命令 | 说明 | 示例 |
|------|------|------|
| `pipeline` | 全流水线 | `bridge pipeline --once` |
| `pipeline --loop` | 持续流水线 | `bridge pipeline --interval 30` |
| `pipeline --dry-run` | 干跑预览 | `bridge pipeline --once --dry-run` |

### 5.5 监控

| 命令 | 说明 | 示例 |
|------|------|------|
| `telemetry` | 遥测报告 | `bridge telemetry` |
| `cost` | 成本报告 | `bridge cost` |
| `cost --project X` | 项目成本 | `bridge cost --project my-project` |
| `adaptive-dispatch` | 自适应派发 | `bridge adaptive-dispatch` |

### 5.6 Web 服务

| 命令 | 说明 | 示例 |
|------|------|------|
| `serve` | 启动 Web 服务 | `bridge serve --host 0.0.0.0 --port 8080` |

## 6. 典型工作流

### 6.1 单任务流程

```bash
# 1. 写任务描述文件
cat > task-001.md << 'EOF'
# Task: 修复登录 bug

## 目标
修复用户登录时 500 错误

## 变更内容
- 检查 auth.py 的异常处理
- 添加输入验证

## 验收标准
- 登录测试通过
- 无 500 错误
EOF

# 2. 创建任务
bridge create -p my-project-w01 -t fix-login --task-file task-001.md

# 3. 派发
bridge auto-dispatch

# 4. 查看状态
bridge status

# 5. Worker 完成后审查
bridge review-pass -t fix-login

# 6. 集成
bridge integrate
```

### 6.2 多 Worker 并行

```bash
# 创建 3 个独立任务，分给 3 个 Worker
bridge create -p my-project-w01 -t feature-a --task-file feature-a.md
bridge create -p my-project-w02 -t feature-b --task-file feature-b.md
bridge create -p my-project-w03 -t feature-c --task-file feature-c.md

# 一次性派发（自动分配到空闲 Worker）
bridge auto-dispatch

# 持续监控
watch -n 5 'bridge status'
```

### 6.3 自动流水线（推荐）

```bash
# 创建任务后，启动自动流水线
# 自动完成: 派发 → 等待 → 审查 → 集成
bridge pipeline --interval 30

# 或单次执行
bridge pipeline --once

# 干跑预览（不实际执行）
bridge pipeline --once --dry-run
```

### 6.4 持续自动派发

```bash
# 持续轮询，有任务就派发
bridge auto-dispatch --loop --interval 10

# 限制最大并发 Worker 数
bridge auto-dispatch --loop --max-workers 3
```

## 7. 任务文件格式

任务文件是 Markdown，结构如下：

```markdown
# Task: <任务标题>

## 目标
<要做什么>

## 变更内容
<改哪些文件/模块>

## 验收标准
<怎样算完成>
```

创建任务时也可以用命令行参数代替文件：

```bash
bridge create -p my-project -t task-001 \
  --objective "修复 bug" \
  --changes "更新 handler.py" \
  --acceptance "测试通过"
```

## 8. 状态机

```
READY → QUEUED → STARTING → RUNNING → REVIEW_REQUIRED → DONE
                                   │                      ▲
                                   ├→ BLOCKED             │
                                   ├→ ASSISTANCE_REQUIRED │
                                   ├→ AUTH_REQUIRED       │
                                   ├→ RETRYABLE           │
                                   └→ FAILED              │
REVIEW_REQUIRED → FIX_REQUIRED → RUNNING (重新执行)
```

| 状态 | 说明 |
|------|------|
| `READY` | 任务已创建，等待派发 |
| `QUEUED` | 已分配 Worker，等待执行 |
| `RUNNING` | Worker 正在执行 |
| `REVIEW_REQUIRED` | Worker 完成，等待审查 |
| `DONE` | 审查通过，已集成 |
| `FIX_REQUIRED` | 审查退回，需修复 |
| `FAILED` | 执行失败 |
| `ASSISTANCE_REQUIRED` | 需要人工介入（硬超时等） |

## 9. systemd 服务管理

```bash
# 启动/停止/重启
sudo systemctl start bridge
sudo systemctl stop bridge
sudo systemctl restart bridge

# 查看状态
sudo systemctl status bridge

# 查看日志
sudo journalctl -u bridge -f          # 实时日志
sudo journalctl -u bridge --since "1 hour ago"

# 开机自启
sudo systemctl enable bridge
sudo systemctl disable bridge
```

## 10. 常见问题

### Q: doctor 报告 SSH 连接失败

```bash
# 检查免密登录
ssh nathan@192.168.1.51 "echo ok"

# 如果需要密码，配置免密：
ssh-copy-id nathan@192.168.1.51

# 检查 ~/.ssh/config 是否有正确配置
```

### Q: Worker 上 codearts 命令找不到

```bash
# 在 Worker 机器上检查
which codearts

# 如果路径不同，更新 workers.json 的 cliPath
# 例如: /home/nathan/.codeartsdoer/installers/bin/codearts
```

### Q: 任务卡在 RUNNING 状态

```bash
# 检查是否有 stale 任务
bridge doctor

# 手动查看任务目录
ls tasks/<task-id>/

# 查看 Worker 日志
ssh nathan@192.168.1.51 "cat /home/nathan/bridge-python/tasks/<task-id>/outbox/worker.log"
```

### Q: 如何查看任务交付物

```bash
# 任务目录结构
tasks/<task-id>/
├── inbox/          # 架构者写入的指令
├── outbox/         # Worker 产出的结果
├── state.json      # 任务状态
└── review/         # 审查记录

# 查看结果
cat tasks/<task-id>/outbox/result.md
```

### Q: 如何添加新 Worker

1. 在 `workers.json` 添加新 Worker 条目
2. 在 `projects.json` 添加对应项目
3. 配置 SSH 免密
4. 运行 `bridge doctor` 验证

### Q: pipeline --dry-run 做什么

干跑模式：显示每一步会做什么，但不实际执行。用于预览流水线计划。

### Q: 如何调整超时

```bash
# 创建时指定
bridge create -p my-project -t task-001 --timeout-minutes 60 --task-file task.md

# 或在 projects.json 中设置 timeoutMinutes
```

## 11. 目录结构

```
bridge-python/
├── src/bridge/           # 源码
│   ├── cli.py            # CLI 入口
│   ├── daemon.py         # 守护进程
│   ├── worker.py         # Worker 管理
│   ├── dispatch.py       # 任务派发
│   ├── architect_loop.py # 架构循环
│   ├── pipeline.py       # 流水线
│   └── transport/        # 传输层
├── tasks/                # 任务目录（运行时生成）
├── workers.json          # Worker 配置
├── projects.json         # 项目配置
├── deploy.sh             # 一键部署脚本
├── DEPLOY.md             # 本文档
└── pyproject.toml        # Python 包定义
```

## 12. 快速验证清单

部署完成后，按以下步骤验证：

```bash
export PYTHONPATH=src

# 1. 环境检查
python3 -m bridge.cli doctor

# 2. 查看 Worker
python3 -m bridge.cli workers

# 3. 查看项目
python3 -m bridge.cli projects

# 4. 创建测试任务
echo "# Test Task\n## 目标\n验证部署\n## 变更内容\n无\n## 验收标准\n无" > test-task.md
python3 -m bridge.cli create -p <项目ID> -t test-001 --task-file test-task.md

# 5. 派发
python3 -m bridge.cli auto-dispatch

# 6. 查看状态
python3 -m bridge.cli status

# 7. 如果状态为 REVIEW_REQUIRED，审查通过
python3 -m bridge.cli review-pass -t test-001

# 8. 集成
python3 -m bridge.cli integrate

# 9. 确认状态为 DONE
python3 -m bridge.cli status
```

全部通过则部署成功。