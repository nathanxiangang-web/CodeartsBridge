# 05 — 真实验收场景

所有收口工作最终必须通过这里，而不是只靠单元测试数量。

## Scenario A — 单 Worker 完整闭环

创建一个非常小的真实代码任务。

期望：

```
READY
-> QUEUED
-> STARTING
-> RUNNING
-> REVIEW_REQUIRED
-> APPROVED
-> INTEGRATING
-> INTEGRATED
-> DONE
```

检查：

- Worker Agent 真的执行 CodeArts。
- Thinking UI 在 RUNNING 时持续有 reasoning/tool 回显。
- `session.log` 有内容。
- RESULT.md / TESTS.md 被回传。
- Review PASS 后尚未集成时，不允许 DONE。
- cherry-pick 后 git HEAD 真变化。
- 集成验证通过后才写 integratedSha。
- DONE 必须和 integratedSha 同时成立。

## Scenario B — 4 Worker 并发

同时创建 4 个互不依赖的小任务。

期望：

```
w01 / w02 / w03 / w04
```

各自只跑 1 个任务。

UI 必须能同时看到 4 个窗口的实时状态。

不要求复杂 worker score，只要求：

- 不重复派发。
- 不超过 capacity=1。
- 完成后 slot 释放。
- 下一批任务能继续派发。

## Scenario C — CodeArts 失败

让任务故意返回非 0。

期望：

- Agent 状态进入 ASSISTANCE_REQUIRED 或明确失败态。
- Bridge 不把任务写成 DONE。
- UI 能看到最后事件和错误。
- 不发生 integration。

## Scenario D — Hard timeout

任务故意睡眠超过 hard timeout。

期望：

- 只有一个组件负责最终 kill。
- Agent Watchdog 结束进程。
- Bridge 收到 terminal 状态。
- 不出现两个 Supervisor 相互抢杀。
- UI 不永远卡在 RUNNING。

## Scenario E — Bridge 重启

RUNNING 中重启 Bridge，但不重启 Worker Agent。

期望：

- Worker 任务继续。
- Bridge 根据 inflight/job id 恢复观察。
- UI 恢复回显。
- 任务最后正常收口。

## Scenario F — Agent 重启

RUNNING 中重启 Agent。

期望：

- Recovery 明确处理原 job。
- 不创建第二份重复任务。
- 最终状态必须可解释，不能永远 RUNNING。

## Scenario G — Review PASS 但 Integration 失败

制造 cherry-pick 冲突或 post-merge test 失败。

期望：

```
APPROVED
-> INTEGRATING
-> INTEGRATION_FAILED
```

禁止：

```
DONE
```

项目仓库必须回滚到明确状态。

## Scenario H — UI 只读

浏览器端只能 GET/观察。

UI 不应出现：

```
Create
Cancel
Retry
Reassign
Review Pass
Review Fix
Project Settings
Worker Settings
```

控制逻辑由 Bridge 内部自动完成，CLI 只保留必要的诊断/救援入口。

## 收口最终门槛

只有 A~H 中与当前目标相关的真实场景通过，才能宣布“功能完成”。

测试文件数量、类数量、模块数量都不能作为完成依据。
