# runtime 模块

> 职责：进程生命周期、超时、取消、事件回显

## 关键文件

- `src/bridge/runtime/process_supervisor.py` — 进程管理（P0-05）
- `src/bridge/runtime/timeout.py` — 软/硬超时（P0-06）
- `src/bridge/runtime/events.py` — 事件回显（P0-08）
- `src/bridge/runtime/heartbeat.py` — 心跳
- `src/bridge/runtime/cancellation.py` — 取消
- `src/bridge/runtime/session.py` — 会话
- `src/bridge/runtime/recovery.py` — 恢复

## 进程生命周期

```
RUNNING → CANCEL_REQUESTED → terminate → grace period → kill if needed → CANCELLED
```

## 超时

```
RUNNING
  ├── soft deadline → request checkpoint → ASSISTANCE_REQUIRED
  └── hard deadline → force kill
```

## 事件流

```
Worker → incremental event reader → sanitized normalizer → events.jsonl → state snapshot → UI
```

事件有单调递增 `seq`，支持类型：status, heartbeat, tool, test, warning, terminal。

## STALE 检测

```
RUNNING + heartbeat fresh → LIVE
RUNNING + heartbeat 超时 → STALE
terminal state → DONE / FAILED / BLOCKED
```

STALE 只是 UI 可观测状态，不改变 canonical task state。