# NEXT — 下一位 AI 从这里开工

先读：

```text
AGENTS.md
README.md
docs/USAGE.md
docs/CODEARTS-PINNED-RUNTIME.md
```

不要先翻旧 roadmap 再猜运行方式。

## 当前已完成

```text
核心 Agent 执行链
artifact archive/fetch
dispatch/scheduler 主路径
review -> APPROVED -> integration -> DONE
Task 真删除 + deferred delete
Tasks / Task Detail 第一轮 UI
CLI / packaging 旧死亡入口清理
legacy integration_service 删除
README / 安装脚本 / 运维入口统一
```

当前安装入口：

```text
deploy/install-bridge.sh
deploy/install-worker-agent.sh
```

## 当前优先级

### P1 — Thinking / Overview

- Thinking 明确区分 live 与 retained history
- Overview 显示 Worker 当前任务 / elapsed / last event
- 继续保持 UI 简洁，不恢复重型控制面

### 已完成 — CodeArts built-in write/edit 调查

26.8.12 固定基线上的受控矩阵和 Agent HTTP 真实 Job 已通过。根因是生效权限文件路径判断错误，叠加 Agent 遗留 `OPENCODE_*` 环境；Bridge 未显式指定 Build 不是根因。

以后部署通过 `deploy/codearts-worker-runtime.py audit` 验收，修复与回滚按 `docs/CODEARTS-WRITE-PERMISSION-RUNBOOK.md` 执行。不要把 shell/python fallback 当成原生 write 验收结果，也不要重新设计 Agent/outbox。

26.9.7 的 Model Queuing package/account gate 仍是独立问题。生产 Worker 禁止执行 `codearts upgrade`；版本恢复与 Release 信息见 `docs/CODEARTS-PINNED-RUNTIME.md`。

### P2 — 控制循环和历史资料收尾

- 验证 `bridge serve --with-pipeline` 长期运行稳定性
- 继续清理误导当前架构的历史说明
- 真实 Scenario A/B/G 再跑一轮

## 不要恢复

```text
bridge-daemon
supervision
policy gate
第二套 runtime supervisor
adaptive scheduler
cost layer
旧 dispatch.py
```

## 验收习惯

代码修改至少：

```bash
python -m pytest -q
python -m bridge.cli --help
python -m bridge.cli doctor
```

涉及真实 Agent/transport/lifecycle 时，再跑真实 task。
