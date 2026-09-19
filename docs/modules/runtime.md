# runtime module

> 职责：进程生命周期、取消、事件回显

## Key files

- `src/bridge/runtime/process.py` — 进程管理
- `src/bridge/runtime/cancellation.py` — 取消
- `src/bridge/runtime/events.py` — 事件回显（P0-08）

## Process lifecycle

```
RUNNING -> CANCEL_REQUESTED -> terminate -> grace period -> kill if needed -> CANCELLED
```

## 事件流

```
Worker -> incremental event reader -> sanitized normalizer -> events.jsonl -> state snapshot -> UI
```

Events have a monotonically increasing `seq`. Supported types: status, heartbeat, tool, test, warning, terminal.

## STALE detection

```
RUNNING + heartbeat fresh -> LIVE
RUNNING + heartbeat timeout -> STALE
terminal state -> DONE / FAILED / BLOCKED
```

STALE 只是 UI 可观测状态，不改变 canonical task state。

> 超时、心跳、会话、恢复由 Agent 主链路处理（agent/watchdog.py, agent/recovery.py, agent/store.py）。
