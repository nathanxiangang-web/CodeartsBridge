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

### 已完成 — CodeArts built-in write/edit

固定基线仍是 **CodeArts CLI 26.8.12 pinned runtime**。

已完成：

```text
permission hang 已消失
授权项目路径上的 built-in write/edit 已恢复
多 Worker 实机写入任务已到 REVIEW_REQUIRED
临时 WRITE_STRATEGY_DIRECTIVE 已删除
```

26.9.7 的 Model Queuing package/account gate 仍是独立的版本兼容问题，生产 Worker 继续禁止 `codearts upgrade`。版本恢复与 Release 信息见 `docs/CODEARTS-PINNED-RUNTIME.md`。

如果未来 editor refusal 回归，先按单机权限/路径/版本漂移排查，不要重新引入一套长期 shell 写入策略。

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
