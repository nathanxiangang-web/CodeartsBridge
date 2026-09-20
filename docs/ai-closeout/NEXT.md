# NEXT — 下一位 AI 从这里开工

先读：

```text
AGENTS.md
README.md
docs/USAGE.md
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

### P1 — CodeArts built-in write/edit 调查

当前事实：

```text
permission hang 已消失
--format json 下 built-in write/edit 仍可能立即拒绝
shell/python fallback 可以写 outbox
```

这里仍是“未彻底解决”，不要写成已完成。

调查顺序：

1. 先做原生 CodeArts 可复现实验
2. 确认最终生效 permission / agent / run mode
3. 区分普通 project path、隐藏目录、external path
4. 有证据后再决定是否改 Bridge

不要先重构 Agent/outbox。

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
