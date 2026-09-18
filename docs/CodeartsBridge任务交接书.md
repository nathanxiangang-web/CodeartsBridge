# CodeartsBridge 任务交接书

> 交接时间: 2026-09-19
> 交出人: 小通 (glm-5.2)
> 项目: CodeartsBridge — AI 任务调度桥

---

## 一、远端代码位置

| 项目 | 路径 |
|------|------|
| **178.50 代码目录** | `/home/nathan/bridge-python` |
| **bridge 服务** | `bridge.service` (systemd) |
| **启动命令** | `python3 -m bridge.cli serve --host 0.0.0.0 --port 8080` |
| **API 地址** | `http://192.168.178.50:8080/api/health` |
| **GitHub 仓库** | `https://github.com/nathanxiangang-web/CodeartsBridge` |
| **分支** | `master` = `main`（已同步） |
| **当前 HEAD** | `7f3870b` config: unify worker environment |

### SSH 连接信息

```
主机: 192.168.178.50
用户: nathan
密码: 647lsx
```

### 部署流程

```bash
# 1. SSH 到 178.50
ssh nathan@192.168.178.50

# 2. 拉取最新代码
cd /home/nathan/bridge-python
git fetch origin && git reset --hard origin/master

# 3. 重启 bridge 服务
sudo systemctl restart bridge.service

# 4. 验证
systemctl is-active bridge.service
curl -s http://localhost:8080/api/health
PYTHONPATH=src python3 -m pytest tests/e2e/ -q
```

---

## 二、已完成任务

### P0 全部完成（5 个 Wave，4 个 commit）

| Wave | Commit | 任务 | 说明 |
|------|--------|------|------|
| 1 | `0cf338c` | P0-01 | `execute_dispatch()` 统一 CLI 和 daemon 调度 |
| 1 | `0cf338c` | P0-02 | `state.py` 持久化 attempt 号 |
| 1 | `0cf338c` | P0-03 | workspace 隔离改为 transport 感知 |
| 1 | `0cf338c` | P0-08 S1 | E2E 测试骨架 + CI workflow |
| 2 | `27bc573` | P0-07 | `result_classifier.py` 纯函数结果分类器 |
| 2 | `27bc573` | P0-04 | `check_host_affinity()` host 匹配检查 |
| 2 | `27bc573` | P0-05 | `ProcessSupervisor` + CANCELLED 状态 |
| 3 | `10ae6e0` | P0-06 | 软超时 checkpoint + ASSISTANCE_REQUIRED |
| 4 | `05c1f93` | P0-08 | `events.py` 事件回显 + 心跳 + STALE 检测 |
| Docs | `531eb5e` | P0-09 | Docs Truth Reset + P0_STATUS.md |

### P1 全部完成（6 个任务）

| Commit | 任务 | 说明 |
|--------|------|------|
| `53fde7d` | P1-01 | 生产级 doctor 探针（10 个检查函数 + 5 种就绪状态） |
| `c190fc8` | P1-02 | 优先级调度（priority/estimatedMinutes/critical-path/worker选择） |
| `d2fa279` | P1-03 | 模型路由（resolve_model + ROLE_MODEL_MAP + transport model 参数） |
| `272f7e7` | P1-06 | 遥测统计（telemetry.py + 状态时间戳 + bridge telemetry 命令） |
| `c1bf53c` | P1-04 | 策略门控（preChecks/postChecks/approvalGate 接入 worker.py） |
| `f9699cd` | P1-05 | 上下文包（11 个文档 + ADR 系统，纯文档路径 A） |

### P2 全部完成（5 个任务）

| Commit | 任务 | 说明 | 状态 |
|--------|------|------|------|
| `d930610` | P2-roadmap | P2 roadmap 文档 | DONE |
| `41f0bab` | P2-01 | auto-dispatch 引擎 + CLI | DONE |
| `140fee2` | P2-02 | architect AI loop（规划+审查） | DONE |
| `23c81bb` | P2-03 | integration automation | DONE |
| `f44e7f8` | P2-04 | conflict resolution | DONE |
| `f44e7f8` | P2-05 | pipeline orchestrator | DONE |

### P3 全部完成（3 个任务）

| Commit | 任务 | 说明 | 状态 |
|--------|------|------|------|
| `2d6c249` | P3-01 | 自适应调度策略（adaptive.py） | DONE |
| `d9ebaaa` | P3-02 | 成本追踪与优化（cost.py） | DONE |
| `0dc9741` | P3-03 | 性能仪表盘 API + UI | DONE |

---

## 三、未完成任务

P0、P1、P2、P3 全部完成。

#### P1-03: 模型配置和角色路由（W02）

- **目标**: 解决 worker.model 和 project.model 存在但 transport 固定 REQUIRED_MODEL 的问题
- **需要支持**:
  - Architect → 最强推理模型
  - Implement → 编码模型
  - Review → 推理模型
  - Test → 快速/低成本模型
- **涉及文件**: `src/bridge/transport/`, `src/bridge/config.py`
- **依赖**: 无

#### P1-04: 最小策略门控（W01）

- **目标**: 接入 preChecks → Worker → postChecks → approvalGate
- **注意**: 不要把 Bridge 做成大型 workflow engine，只做最小接入
- **涉及文件**: 新建 `src/bridge/policy.py` 或 `src/bridge/policy/`
- **依赖**: 无

#### P1-05: 上下文包和 ADR 系统（W02）

- **目标**: 新 Worker 不再重新扫描整个项目
- **需要建立**:
  ```
  docs/
  ├── 00-PROJECT-BLUEPRINT.md
  ├── 01-ARCHITECTURE.md
  ├── 02-DEVELOPMENT-RULES.md
  ├── modules/
  │   ├── dispatch.md
  │   ├── runtime.md
  │   ├── worker.md
  │   ├── transport.md
  │   └── policy.md
  └── decisions/
      ├── ADR-001-worker-isolation.md
      ├── ADR-002-task-state-machine.md
      └── ADR-003-ai-responsibilities.md
  ```
- **派发时给 Worker**: TASK + 相关 module docs + 相关 ADR + 相关 contract + baseline SHA
- **依赖**: 无

#### P1-06: 遥测统计（W03）

- **目标**: 跟踪吞吐量、首次通过率、超时、Worker 利用率
- **至少统计**: taskQueueTime, dispatchLatency, executionDuration, firstPassRate, timeoutRate, workerUtilization
- **涉及文件**: 新建 `src/bridge/telemetry.py`
- **依赖**: 无

---

## 四、关键代码结构

```
src/bridge/
├── cli.py              # CLI 入口（serve/dispatch/doctor/status）
├── daemon.py           # daemon 模式运行
├── dispatch.py         # 核心调度（execute_dispatch, check_host_affinity）
├── state.py            # 状态机（READY→QUEUED→STARTING→RUNNING→REVIEW_REQUIRED→DONE, CANCELLED）
├── worker.py           # Worker 执行逻辑
├── config.py           # 配置解析（ProjectConfig, WorkerConfig, Registry）
├── doctor.py           # P1-01: 生产级健康检查
├── result_classifier.py # P0-07: 结果分类器
├── atomic.py           # 原子文件写入
├── scheduler/          # 调度器包
│   ├── __init__.py     # 已有调度组件
│   ├── priority.py     # P1-02: 优先级调度
│   ├── matcher.py      # 角色匹配
│   ├── dependency.py   # 依赖解析
│   ├── capacity.py     # 容量规划
│   ├── affinity.py     # 亲和性
│   ├── lease.py        # 租约管理
│   └── planner.py      # 调度编排
├── runtime/
│   ├── timeout.py      # P0-06: 软/硬超时
│   ├── events.py       # P0-08: 事件回显
│   └── process_supervisor.py # P0-05: 进程管理
├── transport/
│   └── ssh.py          # SSH 传输
└── api/
    └── server.py       # HTTP API 服务

tests/e2e/              # E2E 测试（121 个）
├── test_lifecycle.py   # 生命周期测试
├── test_result_classifier.py # 结果分类器测试
├── test_p0_wave2.py    # P0 Wave 2 测试
├── test_soft_timeout.py # 软超时测试
├── test_events.py      # 事件回显测试
├── test_doctor.py      # P1-01 doctor 测试
└── test_scheduler.py   # P1-02 调度器测试
```

---

## 五、测试状态

| 环境 | E2E 测试 | Unit 测试 | 总计 |
|------|----------|-----------|------|
| 178.50 (Linux) | 304 | — | **304 passed** (P0+P1+P2+P3 全量) |

---

## 六、4 个 Worker 配置

| Worker ID | 主机 | 角色 |
|-----------|------|------|
| bus-w01-dev | 178.52 | 开发 |
| bus-w02-dev | 178.50 | 开发 |
| bus-w03-dev | 178.53 | 开发 |
| bus-w04-qa | 178.51 | 仅 review/test |

---

## 七、注意事项

1. **commit 签名**: 必须带 `[姓名/模型]`，如 `[小通/glm-5.2]`
2. **部署方式**: SSH 到 178.50 → git pull → systemctl restart bridge.service
3. **测试**: 每次改动后运行 `PYTHONPATH=src python -m pytest tests/e2e/ tests/test_phase*.py -q`
4. **状态机**: READY→QUEUED→STARTING→RUNNING→REVIEW_REQUIRED→DONE，新增 CANCEL_REQUESTED→CANCELLED 和 ASSISTANCE_REQUIRED
5. **事件系统**: events.jsonl 单调递增 seq，支持 STALE 检测，敏感信息遮盖
6. **调度器**: `scheduler/` 是已有包，新代码放入 `scheduler/priority.py`，不要创建 `scheduler.py` 文件
7. **开发文档**: `C:\Users\Nathan\AppData\Local\Programs\OfficeAce\data\uploads\CodeartsBridge-持续开发推进文档 (1) (1).md`
8. **P0 完成状态文档**: `docs/P0_STATUS.md`（已提交到仓库）
