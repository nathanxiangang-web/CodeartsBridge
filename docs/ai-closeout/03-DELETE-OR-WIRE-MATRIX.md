# 03 — Delete / Wire 决策矩阵

状态说明：

- **KEEP**：已经在真实主链使用。
- **WIRE**：有价值，但目前没有真实接线。
- **DELETE**：当前方向明确不需要。
- **VERIFY**：先做引用 + E2E 审计，再决定；默认倾向删除。

| 模块 | 当前判断 | 原因 | 下一动作 |
|---|---|---|---|
| `agent/server.py` | KEEP | Worker Agent 真实入口 | 继续稳定 |
| `agent/runner.py` | KEEP | CodeArts 实际执行 + 回显 | 继续稳定 |
| `agent/watchdog.py` | KEEP | 真实 timeout/process owner | 明确为唯一 Worker kill owner |
| `agent/store.py` | KEEP | Job 状态/事件真实持久化 | 保留 |
| `transport/agent.py` | KEEP | Bridge -> Agent 主 transport | 保留 |
| `worker.py` | KEEP | CLI run 的当前执行入口 | 后续继续瘦身 |
| `web/*` 当前 4 页面 | KEEP | 只读监控真实需求 | 不再扩控制功能 |
| `pipeline.py` | WIRE | review/dispatch/integrate 逻辑存在，但不是 serve 默认控制循环 | 收成唯一 TaskLoop |
| `auto_dispatch.py` + `scheduler/*` | KEEP/瘦身 | pipeline 实际新调度路径 | 替换 legacy dispatch 后再砍无用子模块 |
| `dispatch.py` | DELETE | CLI/daemon 的平行旧调度器 | CLI 迁移后删除 |
| `daemon.py` | DELETE | 第三套长期循环，只 dispatch | 用唯一 Bridge 服务替代 |
| `application/dispatch_service.py` | VERIFY | 与 dispatch / auto_dispatch 重叠 | 选择唯一 API 后删重复 |
| `application/review_service.py` | VERIFY | CLI/API manual review 使用，但 architect_loop 又有另一套 | 合并 review 语义 |
| `application/integration_service.py` | VERIFY/DELETE | 与 integration.py 重叠且是 legacy branch merge 语义 | 默认删除 |
| `architect_loop.py` | KEEP/重写 | polling review 目前是真的，但 PASS 状态是假闭环 | 只负责 review，不伪造 integration |
| `supervision/config.py` | DELETE/大幅瘦身 | migration flags 远多于真实能力 | 留最小配置或直接删除 |
| `supervision/flags.py` | DELETE | 迁移期 feature flags | 收口后不需要 |
| `supervision/background.py` | DELETE | 默认关闭，非核心 | 删除 |
| `supervision/capacity.py` | DELETE | 默认关闭，scheduler 已有 capacity | 删除重复 |
| `supervision/review_lock.py` | DELETE | 当前单 Bridge 进程目标不需要第二套锁 | 用状态幂等替代 |
| `supervision/queue.py` | VERIFY | event review 默认关闭，queue 无稳定长期生产者 | 无真实 E2E 就删 |
| `supervision/reactor.py` | VERIFY | 当前默认关闭，多个 handler 默认 no-op | 无真实 E2E 就删 |
| `supervision/supervisor.py` | VERIFY | pipeline 默认实例没有真实 task schedule | 优先用 Agent Watchdog + stale check 替代 |
| `runtime/supervisor.py` | VERIFY/DELETE | 与 Agent Runtime 重叠，不在当前 Agent 主链 | 引用审计后删 |
| `runtime/process_supervisor.py` | VERIFY/DELETE | 第二套 process lifecycle | 删除重复 owner |
| `policy/*` | DELETE | Worker 主链已退出 Policy Gate | 删除代码/测试/文档 |
| `adaptive.py` | DELETE | 非核心且增加调参复杂度 | 删除 CLI + tests |
| `cost.py` | DELETE | 当前内部项目不需要成本控制面 | 删除 |
| `telemetry.py` | VERIFY | UI 可保留少量指标，但不需要独立复杂 CLI | 砍成最小统计 |
| `interfaces/mcp/*` | VERIFY | 与核心执行无关 | 不默认启动；无真实用户则删 |
| `ssh_shell.py` | DELETE | Agent 主 transport 后低价值 | 删除 |
| `remote_worktree.py` | VERIFY/DELETE | 与 Local-First/Agent 主路径冲突 | 先迁移 integration 依赖再删 |
| `workspace/policy.py` | DELETE/瘦身 | 当前 Agent 强制 existing，矩阵复杂 | 收成 existing + 可选 worktree |
| `state.py` + `core/state.py` | WIRE | 两套状态 API 仍同时被引用 | 统一成一套后删除另一套 |
| `README.md` | REWRITE | 仍描述 10 页 UI/Token/旧配置 | 以当前代码重写 |
| `deploy/bridge-daemon.service` | DELETE/REPLACE | 指向旧 daemon 和旧路径 | 改成唯一 Bridge 服务 |

## 删除前必须执行的三步

任何 DELETE 项都必须：

1. 全仓搜索 import / symbol / CLI / systemd / tests。
2. 跑目标真实 E2E，确认替代能力存在。
3. 删除代码时同步删测试和文档，不留“幽灵功能”。

禁止为了保留旧测试而恢复已经退出架构的功能。
