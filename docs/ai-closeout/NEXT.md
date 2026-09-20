# NEXT — 下一位 AI 直接从这里开工

审计基线：`main@e1db59b`

项目已完成核心收口，不再继续大改 Agent / Scheduler / Lifecycle。

先读：

```
docs/ai-closeout/07-PRODUCTIZATION-ROADMAP.md
docs/ai-closeout/08-TASK-DELETION-SEMANTICS.md
```

## 已完成（本轮）

```
P0  CLI / packaging 死入口清理 + CLI contract regression
P1  Tasks 页面：12 状态筛选 + 活跃优先排序 + 时间列 + 删除按钮
P1  Task Detail：outbox 预览 + RESULT/TESTS/DIFF + commitSha + 时间线 + 删除按钮
P2  删除 application/integration_service.py，API/MCP 改用 canonical integrate_task
08  DELETE /api/tasks/<taskId>：200 立即删除 / 202 延迟删除
08  .delete-requested marker：scanners 跳过，auto_dispatch 每轮 finalize
08  UI：一键删除已结束 + 逐行删除，替换 localStorage 隐藏
08  终态任务残留 inflight.json 不阻止删除
```

## 当前优先级

### P1 剩余：Thinking + Overview

```
1. Thinking：明确区分 live 与 retained history
2. Overview：Worker 当前任务 / elapsed / last event
```

### P2 剩余：控制循环收口

```
1. 是否把唯一 TaskLoop 并入 bridge serve
2. 确认 auto_dispatch / integrate_loop / architect_loop 三个循环的触发与协调
```

### P3：文档与部署真相同步

```
1. README 更新为当前真实行为
2. deploy 指引与 systemd 服务一致
3. runtime truth 最终确认
```

## 已完成，不要重复

```
Issue #38
Agent outbox archive lifecycle
Review -> APPROVED -> real Integration -> DONE
dispatch 统一到 auto_dispatch + scheduler
supervision / policy / runtime / daemon / dispatch / adaptive / cost 主模块删除
PR #35 task display clear（localStorage 隐藏已替换为真正删除）
legacy integration_service.py 已删除
DELETE /api/tasks/<taskId> 已实现
```

CodeArts `--format json` 下 built-in write/edit 的立即拒绝视为 CLI 限制；当前 bash fallback 是已验证路径，不再围绕它重构 Agent。

完整工作安排见：

```
docs/ai-closeout/07-PRODUCTIZATION-ROADMAP.md
```
