# ADR-002: 任务状态机

> 状态: Accepted | 日期: 2026-09-18

## 背景

需要明确任务生命周期状态和转换规则。

## 决策

采用以下状态机：

```
READY → QUEUED → STARTING → RUNNING → REVIEW_REQUIRED → DONE
                                    ↓
                              BLOCKED / ASSISTANCE_REQUIRED / AUTH_REQUIRED
                              RETRYABLE / FAILED / CANCELLED

REVIEW_REQUIRED → FIX_REQUIRED → QUEUED（重试）
RUNNING → CANCEL_REQUESTED → CANCELLED
```

状态转换时自动记录时间戳（write-once，不覆盖）：
- QUEUED → queuedAt
- STARTING → startedAt
- RUNNING → runningAt
- REVIEW_REQUIRED → finishedAt
- DONE → doneAt
- FIX_REQUIRED → reviewedAt
- CANCELLED → cancelledAt
- FAILED → failedAt
- BLOCKED → blockedAt

## 理由

- 明确区分"候选"（READY/FIX_REQUIRED/RETRYABLE）、"活跃"（QUEUED/STARTING/RUNNING）、"终态"（DONE/FAILED/BLOCKED/CANCELLED）
- CANCELLED 是显式终态，不误判为 FAILED
- ASSISTANCE_REQUIRED 不是失败，是请求协助
- 时间戳 write-once 避免重试时丢失首次时间

## 影响

- P0-02: attempt 持久化，重试不覆盖旧日志/patch
- P0-05: CANCELLED 状态
- P0-06: ASSISTANCE_REQUIRED 状态
- P1-06: 时间戳用于遥测统计