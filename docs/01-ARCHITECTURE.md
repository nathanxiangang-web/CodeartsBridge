# CodeartsBridge 架构

> 版本: 2.0.0 | 更新: 2026-09-18

## 代码结构

```
src/bridge/
├── cli.py                    # CLI 入口（serve/dispatch/doctor/status/telemetry）
├── daemon.py                 # daemon 模式运行
├── dispatch.py               # 核心调度（execute_dispatch, check_host_affinity）
├── state.py                  # 状态机 + 自动时间戳
├── worker.py                 # Worker 执行逻辑（含 policy 门控）
├── config.py                 # 配置解析（ProjectConfig, WorkerConfig, Registry）
├── doctor.py                 # 生产级健康检查
├── result_classifier.py      # 结果分类器
├── telemetry.py              # 遥测统计
├── atomic.py                 # 原子文件写入
├── codearts.py               # CodeArts CLI 封装 + 模型路由
├── git_ops.py                # Git 操作
├── task.py                   # 任务管理
├── progress.py               # 进度显示
├── scheduler/                # 调度器包
│   ├── priority.py           # 优先级调度
│   ├── matcher.py            # 角色匹配
│   ├── dependency.py         # 依赖解析
│   ├── capacity.py           # 容量规划
│   ├── affinity.py           # 亲和性
│   ├── lease.py              # 租约管理
│   └── planner.py            # 调度编排
├── runtime/
│   ├── timeout.py            # 软/硬超时
│   ├── events.py             # 事件回显
│   ├── heartbeat.py          # 心跳
│   ├── process_supervisor.py # 进程管理
│   ├── cancellation.py       # 取消
│   ├── session.py            # 会话
│   └── recovery.py           # 恢复
├── transport/
│   ├── base.py               # 传输基类
│   ├── local.py              # 本地传输
│   ├── ssh.py                # SSH 传输
│   ├── ssh_shell.py          # SSH-shell 传输
│   └── remote_worktree.py    # 远程 worktree 传输
├── policy/
│   ├── engine.py             # 策略引擎（profile 加载/验证）
│   ├── runtime.py            # 策略运行时（check 执行）
│   ├── integration.py        # 策略接入（preCheck/postCheck/approvalGate）
│   └── timeout.py            # 超时策略
├── api/server.py             # HTTP API 服务
└── application/              # v2 应用服务层
```

## 状态机

```
READY → QUEUED → STARTING → RUNNING → REVIEW_REQUIRED → DONE
                                    ↓
                              BLOCKED / ASSISTANCE_REQUIRED / AUTH_REQUIRED
                              RETRYABLE / FAILED / CANCELLED

REVIEW_REQUIRED → FIX_REQUIRED → QUEUED（重试）
```

状态转换时自动记录时间戳：queuedAt, startedAt, runningAt, finishedAt, doneAt, reviewedAt, cancelledAt 等。

## 模型路由

优先级：worker.model > project.model > ROLE_MODEL_MAP[role] > REQUIRED_MODEL

角色映射：
- architect → 推理模型
- implement → 编码模型
- review → 推理模型
- test → 快速模型

## 策略门控

```
preChecks → Worker → postChecks → approvalGate → REVIEW_REQUIRED
```

- preCheck 失败（onFailure=block）→ BLOCKED，不执行 Worker
- postCheck 失败（onFailure=block）→ BLOCKED
- approvalGate → REVIEW_REQUIRED（等待批准）
- 无 policy profile → 跳过（向后兼容）

## 事件流

```
CodeArts/Worker → incremental event reader → sanitized normalizer
→ events.jsonl → state heartbeat snapshot → UI
```

- 事件有单调递增 seq
- STALE 检测：RUNNING + heartbeat 超时 → STALE（不改变 canonical state）
- 敏感信息遮盖
- 不暴露模型私有 reasoning