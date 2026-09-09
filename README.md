# Codex ↔ GLM Worker Bridge

`E:\Obsidian\codex-glm` 是架构师端（Codex）与执行端（CodeArts Agent / GLM Worker）之间的文件通信桥梁。

正式运行不依赖界面自动化：Codex 发布任务文件，本地调度器调用 CodeArts CLI，GLM Worker 自主完成搜索、修改、测试和构建，然后把压缩结果写回任务目录。

## 当前默认

- 新项目默认 `runMode: auto`，不启用沙箱限制。
- 默认模型固定为 `huaweicloud-maas/GLM-5.2`，与 GLM Worker 角色一致。
- 同一个项目同时只运行一个任务。
- 任务文件、Worker 结果和调度状态分别由不同角色写入。
- 生产发布、系统配置等边界由任务本身定义，不在桥梁层写死。
- 本地与 SSH 虚拟机使用同一套任务协议；传输差异由调度器适配。
- 虚拟机未安装 CodeArts CLI 时使用 `ssh-shell`：本机 CLI 通过已有 SSH 别名操作远端源码，不向虚拟机复制华为凭证。

## 会话复用（v1.1）

- 首次 attempt 调用 CodeArts 时附加 `--format json --title <task-id>`，从 stdout 的 JSON Lines 事件中提取 `sessionID`、最后事件时间和 `step_finish.part.tokens` token 统计。
- 遥测保存到 `state.json` 的 `sessionId`、`sessionMode`（`new`/`resume`）、`lastEventAt`、`tokens` 字段；字段缺失时允许为 `null`。
- 同一任务后续 attempt 若已有 `sessionId`，使用 `codearts run --session <id>` 续跑，不默认 fork；session ID 只接受 `^[A-Za-z0-9_-]+$`。
- `Set-State` 基于旧 state 合并更新，不会因最终状态写入而丢失已记录的会话和遥测字段；旧版 state 文件无需迁移即可读取。
- 整改/恢复任务必须获得原始 TASK 和相关 FIX 的完整最小上下文：Runner 在 prompt 中列出 inbox 中全部指令文件，以最后一份为准但要求 Worker 结合前置背景。
- `local`、`ssh-shell`、`ssh` 三种 transport 使用一致的会话语义；远端 shell 参数通过 `Quote-Posix` 安全引用，session ID 校验后再拼入命令。

## 双 Worker 派发（v1.1）

- `bridge.ps1 dispatch` 一次性派发，默认 `MaxWorkers = 2`。
- 非阻塞启动子 PowerShell 进程执行 `run -TaskId`，默认打开独立 PowerShell 窗口显示心跳和事件摘要；`-Quiet` 才隐藏窗口。使用全局 `dispatcher.lock` 文件锁防止重复领取。
- 派发前原子地把任务置为 `QUEUED`；`run` 接受 `QUEUED`。活跃数统计 `QUEUED`、`STARTING`、`RUNNING`，不得超过 `MaxWorkers`。
- 候选状态仅限 `READY`、`FIX_REQUIRED`、`RETRYABLE`；不会自动重跑 `BLOCKED`、`FAILED`、`AUTH_REQUIRED`。
- 当前阶段仍实行同一 `projectId` 最多一个活跃任务：不同项目可以并行，同项目不会双派发。
- 派发失败时恢复任务原状态并记录明确错误，不留下永久 `QUEUED`。
- `runtime/logs/dispatcher/` 存放派发摘要 JSON；Worker stdout/stderr 写入 `runtime/logs/<task-id>.attempt-NNN.stdout.log` 和 `.stderr.log`。
### 可见窗口行为

- 默认派发打开独立 PowerShell 小黑窗，显示任务/项目/attempt/session/pid/elapsed 心跳（每5秒），心跳含 `events=`/`思考=`/`工具=` 三个累计计数（已处理的 stdout 事件、thinking/reasoning 摘要、tool_use 摘要行数），以及逐行公开事件摘要（事件类型、工具名、公开文本）。
- 思考块（reasoning/thinking）以 `[思考]` 前缀公开显示正文，与普通公开文本同样经过敏感信息遮盖（AK/SK/Bearer/password/token/secret/api_key → `***`）和 160 字单行截断；`--thinking` 已默认启用（`New-WorkerRunArguments` 统一附加）。Worker prompt 默认要求 reasoning、工具摘要、控制台事件文本与正式交付全部使用纯英文 ASCII，避免中文、智能引号、长破折号等非 ASCII 字符经过控制台传输后乱码。无法提取正文时显示 `[思考] type=<type>`。完整原始 stdout/stderr 保留在本地 attempt 日志。
- 结束时无论 `REVIEW_REQUIRED` 还是 FAILED/BLOCKED/AUTH_REQUIRED/RETRYABLE/CANCELLED，都先把 outbox 的 `RESULT.md`（最多前 20 行）和 `TESTS.md`（最多前 15 行）摘要直接打进窗口（经敏感信息遮盖），再打印现有状态行；outbox 完全为空时打印「outbox 为空，无结果可显示」。成功/`REVIEW_REQUIRED` 随后约5秒后自动关闭；异常状态等待按 Enter。
- `-Quiet` 隐藏窗口并压制控制台进度，但不影响日志落盘和遥测解析。

- `-DryRun` 无副作用模式只输出调度决策，不启动 CodeArts，供测试验证。
- 同项目并发写入仍未开放：后续必须依赖独立 Git worktree 才能安全并行同一项目的多个任务。

## 入口

```powershell
# 初始化目录
pwsh -File .\scripts\bridge.ps1 bootstrap

# 检查环境
pwsh -File .\scripts\bridge.ps1 doctor

# 查看全部项目和任务
pwsh -File .\scripts\bridge.ps1 status

# 一次性派发最多两个不同项目的任务
pwsh -File .\scripts\bridge.ps1 dispatch -MaxWorkers 2

# 仅查看调度决策，不启动 Worker
pwsh -File .\scripts\bridge.ps1 dispatch -DryRun

# 可选：静默派发（不打开窗口，不显示进度）
pwsh -File .\scripts\bridge.ps1 dispatch -Quiet
```

完整流程见 [protocol/PROTOCOL.md](protocol/PROTOCOL.md)。

## CodeArts CLI 授权

CLI 与 CodeArts Agent IDE 的登录状态相互独立。首次运行前需按华为云官方指引配置 `CODEARTS_CLI_AK` 和 `CODEARTS_CLI_SK`；Bridge 只检查变量是否存在，不打印、记录或复制其值。

配置后重新运行 `doctor`，两个授权变量均显示 `true`，再投递 Worker 任务。

## CodeArts CLI 定位

`Find-CodeArtsCli` 在 Windows 上优先返回真实 `codearts.exe`：先查 PATH 中的 `codearts.exe`，再解析 PATH 中的 `codearts.cmd`/`.bat` shim 还原其调用的 `.exe`，最后回退到已知安装目录下的 `.exe`。不会因为 `codearts.cmd` 排在 PATH 前面而拒绝启动，也不通过 shell 拼接不可信参数。
