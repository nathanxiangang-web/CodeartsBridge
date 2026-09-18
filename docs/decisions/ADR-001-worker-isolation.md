# ADR-001: Worker 隔离方式

> 状态: Accepted | 日期: 2026-09-18

## 背景

多 Worker 并行时需要隔离，避免互相污染工作区。

## 决策

隔离方式由 transport 决定，不由 workspaceMode 决定。

| transport + role | 隔离方式 |
|-----------------|---------|
| local + implement | local isolated worktree |
| remote-worktree + implement | remote isolated workspace |
| ssh + implement | existing exclusive |
| review/test | shared readonly（满足安全条件时） |

## 理由

- transport 本身决定了执行环境（本地/远程），隔离方式应与之匹配
- 旧的 workspaceMode 配置与 remote-worktree transport 冲突
- review/test 不需要写隔离，shared readonly 提高效率

## 影响

- P0-03 实现：remote-worktree 不再被 "worktree only supported for local" 拒绝
- existing 同路径只能一个写任务
- readonly 不允许和写任务冲突