# Bridge Protocol v1.2

## 1. 角色与文件所有权

任何可变文件只能有一个写入者，避免两个模型互相覆盖。

| 文件 | 唯一写入者 | 用途 |
|---|---|---|
| `META.json`、`inbox/*.md` | Architect | 项目、目标、约束、验收和整改要求 |
| `outbox/*` | GLM Worker | 结果、测试、阻塞与精简证据 |
| `state.json`、`runtime/locks/*` | Runner | 状态机、进程与项目互斥 |

所有正式消息先写入同目录的 `.tmp` 文件，再原子改名为最终文件。接收方不读取 `.tmp` 文件。

## 2. 任务目录

```text
tasks/<task-id>/
├─ META.json
├─ inbox/
│  ├─ 001-TASK.md
│  └─ 002-FIX.md
├─ outbox/
│  ├─ RESULT.md
│  ├─ DIFF.stat
│  ├─ TESTS.md
│  └─ BLOCKER.md
├─ evidence/
└─ state.json
```

源码不复制到桥梁目录。`META.json` 指向实际项目位置；日志只保留到 `runtime/logs/<task-id>`，默认不进入架构师上下文。

## 3. 状态机

```text
READY -> QUEUED -> STARTING -> RUNNING -> REVIEW_REQUIRED -> DONE
                                  |                      ^
                                  +-> BLOCKED            |
                                  +-> ASSISTANCE_REQUIRED|
                                  +-> AUTH_REQUIRED      |
                                  +-> RETRYABLE          |
                                  +-> FAILED             |
REVIEW_REQUIRED -> FIX_REQUIRED -> RUNNING
```

- `READY`：任务已完整发布。
- `QUEUED`：Dispatcher 已领取，等待子 Runner 启动。
- `STARTING`：Runner 已取得项目锁，正在构造 Worker 进程。
- `RUNNING`：Worker 进程已启动。
- `REVIEW_REQUIRED`：Worker 已生成完整交付物。
- `BLOCKED`：Worker 按规定提交了架构性阻塞。
- `ASSISTANCE_REQUIRED`：Worker 已安全保存检查点，当前任务需要拆分为新的短任务继续。
- `AUTH_REQUIRED`：CLI 可运行，但当前进程没有 CodeArts CLI 授权。
- `RETRYABLE`：模型排队等临时条件超过本次等待时间，可以原任务重试。
- `FIX_REQUIRED`：Architect 发布了下一序号的 `FIX.md`。
- `DONE`：Review 通过。
- `FAILED`：CLI、传输或协议失败；不得伪装成业务阻塞。

## 4. 会话复用

- 首次 attempt 调用 CodeArts 时附加 `--format json --title <task-id>`，从 stdout JSON Lines 提取 `sessionID`、最后事件时间和 token 统计，写入 `state.json` 的 `sessionId`/`sessionMode`/`lastEventAt`/`tokens`。
- 后续 attempt 若已有 `sessionId`，使用 `codearts run --session <id>` 续跑，不默认 fork。session ID 只接受 `^[A-Za-z0-9_-]+$`。
- `Set-State` 合并更新，保留已记录的遥测字段；旧 state 无需迁移。
- 整改/恢复任务在 prompt 中列出 inbox 全部指令文件，以最后一份为准但要求 Worker 结合前置 TASK/FIX 背景，不能只读一个失去背景的 FIX 文件。
- `local`、`ssh-shell`、`ssh`、`remote-worktree` 会话语义一致；远端参数通过 `Quote-Posix` 安全引用。

## 5. 四 Worker 派发

- `dispatch` 一次性派发，默认 `MaxWorkers = 4`，非阻塞启动子 PowerShell 进程执行 `run -TaskId`，默认打开可见窗口。
- 全局 `dispatcher.lock` 文件锁防止重复领取；派发前原子置 `QUEUED`；活跃数（`QUEUED`+`STARTING`+`RUNNING`）不超过 `MaxWorkers`。
- 候选状态仅限 `READY`、`FIX_REQUIRED`、`RETRYABLE`。同一远端工作区最多一个写任务；同一源码可通过绑定不同主机的多个 `remote-worktree` 项目配置并行。
- 派发失败恢复原状态，不留永久 `QUEUED`。`runtime/logs/dispatcher/` 存放派发摘要 JSON；Worker 日志为 `runtime/logs/<task-id>.attempt-NNN.stdout.log` 和 `.stderr.log`。
- 默认窗口显示任务/项目/attempt/session/pid/elapsed 心跳（每5秒）和逐行公开事件摘要；Worker 生成的 reasoning、工具摘要、事件文本与正式交付默认使用纯英文 ASCII，避免中文和其他非 ASCII 标点经过控制台传输后乱码；凭据在摘要中遮盖为 `***`，完整原始 stdout/stderr 保留在 attempt 日志。
- 成功/`REVIEW_REQUIRED` 显示最终状态与日志路径，约5秒后自动关闭；异常状态等待按 Enter。`-Quiet` 隐藏窗口并压制控制台进度，但不影响日志和遥测。
- `-DryRun` 只输出调度决策，不启动 CodeArts。
- `existing` 工作区不允许并发写；模块化并行必须使用独立 `remote-worktree` 工作区，结果以 `refs/worker/<task-id>/result` 回收到集成仓库后再 Review 和合并。

## 6. 模式与环境

`runMode` 支持 `auto`、`manual`、`sandbox`，默认是 `auto`。桥梁不把沙箱作为兼容前提。

项目支持：

- `local`：CodeArts CLI 与项目位于当前 Windows 主机。
- `ssh`：项目与 CodeArts CLI 位于虚拟机，Runner 使用现有 SSH 配置传入任务并取回结果。
- `ssh-shell`：CodeArts CLI 位于当前 Windows，Worker 使用现有免交互 SSH 配置操作虚拟机项目，正式交付仍写回本地任务目录。
- `remote-worktree`：桥接机从干净集成仓库导出指定基线，每个远端 Worker 在自己的任务目录建立独立仓库、运行独立 CodeArts 账号并提交结果；桥接机只导入 namespaced ref，不自动修改主线。

所有远端模式均要求免交互 SSH；Runner 只检查远端 CLI 授权是否可用，不读取、打印、存储或跨主机复制密码、AK、SK。

## 7. 正常交付

Worker 完成后必须生成：

1. `RESULT.md`：修改文件列表、核心改动、尚存风险。
2. `DIFF.stat`：Git diff 统计；非 Git 项目说明原因。
3. `TESTS.md`：实际执行的 lint、typecheck、test、build 及结果。

只有遇到架构选择、公共 API、数据库 Schema、安全认证、数据一致性或明显兼容性冲突时，才生成 `BLOCKER.md`。普通编译和测试问题由 Worker 自行循环解决。

## 8. Review

Architect 优先读取 `RESULT.md`、`DIFF.stat`、`TESTS.md` 和目标 Git Diff，不重新扫描整个项目。

- 通过：写入 `inbox/<seq>-PASS.md`，Runner 归档任务。
- 整改：写入 `inbox/<seq>-FIX.md`，只描述增量问题和验收方法。
- 重大设计问题：写入 `inbox/<seq>-ARCHITECTURAL_BLOCKER.md`。

## 9. 控制

- `runtime/PAUSE`：暂停派发新任务，不中断正在运行的 Worker。
- `tasks/<id>/CANCEL_REQUESTED`：请求停止指定任务并保留现场。
- `runtime/locks/<project-id>.lock`：项目互斥锁。
- `runtime/locks/dispatcher.lock`：Dispatcher 全局互斥锁。
- 超时只终止本次 Worker 进程，不删除源代码、工作区或任务证据。

## 10. 有界任务、软时限与拆分

- 一个任务必须保持单一主要交付物和单一主要故障域；跨两个以上核心边界的工作必须声明依赖并拆成短任务。
- 默认工程实现任务按 10 分钟内可交付设计，硬时限不超过 15 分钟。长时间但范围固定的压力测试可单独提高硬超时，不得借此扩大实现范围。
- Worker 默认只产出单一实现补丁或同类测试；Architect 负责集成、跨平台复跑、真实环境联调与发布门。
- 编辑器、权限、路径、转义或命令构造问题连续失败两次后，Worker 必须立即交检查点并求援，不得继续用临时拼接脚本消耗至硬超时。
- Runner 可以配置软时限。软时限不是失败：Worker 应写入 `outbox/CHECKPOINT.md` 和 `outbox/ASSISTANCE_REQUEST.md`，Runner 将状态置为 `ASSISTANCE_REQUIRED` 并保留仓库、worktree、分支、日志和证据。
- Architect 收到协助请求后，只处理已完成结果和剩余边界；不得把多个新增模块继续追加到原会话。剩余工作以新 task ID、新 CodeArts 会话和最小验收标准派发。
- 因任务过大而主动取消时，取消只终止 Worker 进程；不得清理隔离项目或覆盖当前修改。后继任务必须明确其前置 task ID 与复用的隔离工作区。
- `FIX` 仅用于同一交付物的窄整改。新增模块、真实环境联调、发布审批、回滚演练分别建立后继任务。
- 推荐拆分顺序为：基础能力 -> 单元/行为测试 -> 真实环境联调 -> 集成审查 -> 发布验收。每一步都可独立 Review 和回退。
