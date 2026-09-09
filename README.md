# Codex ↔ GLM Worker Bridge

`codex-glm` 是架构师端（Codex）与执行端（CodeArts Agent / GLM Worker）之间的文件通信桥梁。

桥运行在 Linux（192.168.178.52），架构师发布任务文件，调度器调用远端 CodeArts CLI，GLM Worker 自主完成搜索、修改、测试和构建，然后把压缩结果写回任务目录。Windows 退化为纯 SSH 客户端 + 编辑器，不再安装 CodeArts CLI。

## 当前默认
- 先读`文件下\tests\remote.md`了解你现在可指挥的worker有几个后续进行指挥工作
- 新项目默认 `runMode: auto`，不启用沙箱限制。
- 默认模型固定为 `huaweicloud-maas/GLM-5.2`，与 GLM Worker 角色一致。
- 同一份源代码可通过 4 个 `remote-worktree` 项目配置并行运行；每个 Worker 使用独立账号、主机和任务工作区。
- 任务文件、Worker 结果和调度状态分别由不同角色写入。
- 生产发布、系统配置等边界由任务本身定义，不在桥梁层写死。
- 本地与 SSH 虚拟机使用同一套任务协议；传输差异由调度器适配。
- 所有 4 worker 均在 Linux 上跑各自 CodeArts CLI + 账号，真并行。

## Transport 架构（v1.2）

四种 transport 各司其职。Worker 的 `ssh` 表示 CLI 连接方式，项目的 `remote-worktree` 表示源码隔离方式，两者可以配合使用：

| transport | CLI 位置 | 认证账号 | 并发模型 | 适用场景 |
|-----------|---------|---------|---------|---------|
| `local` | 本机 codearts | 本机账号 | 单进程 | 本地开发、selftest |
| `ssh-shell` | 本机 codearts | 本机账号 | 共用本机 CLI，上限 1-2 | 远端无 CLI 时降级方案 |
| `ssh` | 远端 codearts | 远端各自账号 | 每 worker 独立远端 CLI+账号，真并行 | 生产多 worker 协同（当前默认） |
| `remote-worktree` | 远端 codearts | 远端各自账号 | 每任务独立仓库和分支 | 同一源码按模块并行开发（CloudSite 默认） |

`ssh` transport（`Invoke-SshWorker`，bridge.ps1:1350）流程：
1. 本地 `git bundle` 导出基线源码 → scp 到远端 `remoteBridgeRoot`
2. 远端 init repo + fetch bundle 建立隔离工作区
3. 远端 `codearts run`（远端 CLI + 远端账号 AK/SK）执行任务
4. 结果 outbox scp 回本地 task 目录

当前 4 worker 账号映射（ssh transport）：

| worker | host | 远端账号 | 项目 |
|--------|------|---------|------|
| worker-01-remote | nathan@192.168.178.52 | win1649 (GT-nathanxia) | codex-glm-ma-w01 |
| worker-02-remote | nathan@192.168.178.50 | 8080 (pyjcc-jc) | codex-glm-ma-w02 |
| worker-03-remote | root@192.168.5.15 | rocky1043 | codex-glm-ma-w03 |
| worker-04-remote | nathan@192.168.178.51 | ubuntu5390 | codex-glm-ma-w04 |

`ssh` transport 必需字段：`sshHost`、`remoteBridgeRoot`（远端任务根目录，须绝对路径如 `/home/nathan/.codex-glm-bridge`，scp 不展开 ~）、`remoteCliPath`（可选，缺省 `codearts`）。worker.cliPath 优先于 project.remoteCliPath。

`remote-worktree` 项目由桥接机上的干净集成仓库导出基线 bundle，在目标 Worker 主机的 `remoteWorkspaceRoot/<task-id>/repo` 建立独立副本。Worker 提交后，桥把结果导入集成仓库的 `refs/worker/<task-id>/result`；架构师检查 `RESULT.md`、`DIFF.stat`、`TESTS.md` 和必要 diff，再按依赖顺序合并。Worker 不直接写 178.50 主线。

CloudSite 使用 `cloudsite-rc1-w01` 到 `cloudsite-rc1-w04` 四个项目配置，分别绑定四台 Worker 主机。四个任务可以同时开发不同模块；可能修改同一文件或同一迁移版本的任务仍应由架构师串行合入并处理冲突。

### CloudSite 四副本实用流程

1. 先在桥接机的集成仓库确认主线干净并记录 `HEAD`。任务文件只写英文 ASCII，并把模型、业务逻辑、API、前端等边界拆开。
2. 分别用四个项目和四个 Worker 创建任务；`-Baseline` 固定为派发时记录的提交，避免后来的主线变化悄悄进入运行中的任务。
3. 使用 `dispatch -MaxWorkers 4` 并行启动。每个任务会在自己的远端目录和 Git 分支中运行，不共享可写工作区。
4. 任务进入 `REVIEW_REQUIRED` 后，只读 `RESULT.md`、`DIFF.stat`、`TESTS.md` 和必要 diff。通过后执行 `review-pass`，再按模型/迁移、业务逻辑、API、前端的依赖顺序整合 `refs/worker/<task-id>/result`。
5. 每合入一个结果就更新集成主线；给空闲 Worker 创建后继写任务时使用新的 `HEAD`。不要把仍基于旧模型的后继任务直接并发到共享边界。

```powershell
$baseline = git -C <integration-repo> rev-parse HEAD

pwsh -File .\scripts\bridge.ps1 create -ProjectId cloudsite-rc1-w01 -WorkerId cloud-worker-01 -Role implement -WorkspaceMode existing -TaskId <model-task> -TaskFile <task-file> -Baseline $baseline -TargetMinutes 10 -SoftTimeoutMinutes 12 -TimeoutMinutes 15
pwsh -File .\scripts\bridge.ps1 create -ProjectId cloudsite-rc1-w02 -WorkerId cloud-worker-02 -Role implement -WorkspaceMode existing -TaskId <logic-task> -TaskFile <task-file> -Baseline $baseline -TargetMinutes 10 -SoftTimeoutMinutes 12 -TimeoutMinutes 15
pwsh -File .\scripts\bridge.ps1 create -ProjectId cloudsite-rc1-w03 -WorkerId cloud-worker-03 -Role implement -WorkspaceMode existing -TaskId <api-task> -TaskFile <task-file> -Baseline $baseline -TargetMinutes 10 -SoftTimeoutMinutes 12 -TimeoutMinutes 15
pwsh -File .\scripts\bridge.ps1 create -ProjectId cloudsite-rc1-w04 -WorkerId cloud-worker-04 -Role implement -WorkspaceMode existing -TaskId <web-task> -TaskFile <task-file> -Baseline $baseline -TargetMinutes 10 -SoftTimeoutMinutes 12 -TimeoutMinutes 15

pwsh -File .\scripts\bridge.ps1 dispatch -MaxWorkers 4
pwsh -File .\scripts\show-progress.ps1 -TaskId <task-id>
pwsh -File .\scripts\bridge.ps1 review-pass -TaskId <task-id>
```

这里的项目 transport 已经是 `remote-worktree`；`-WorkspaceMode existing` 表示 Worker 写它本次临时复制出来的独立仓库，不是让四个 Worker 写同一个源目录。账号授权和远端登录只保存在各自 Worker 主机，桥不会复制或打印凭据。

远端 bashrc 注意：Ubuntu 顶部 `case $- in *i*) ;; *) return;;` 会挡住非交互 shell 读取后续 export，需把 `CODEARTS_CLI_AK/SK` export 移到 `case $-` 之前。

## 会话复用（v1.1）

- 首次 attempt 调用 CodeArts 时附加 `--format json --title <task-id>`，从 stdout 的 JSON Lines 事件中提取 `sessionID`、最后事件时间和 `step_finish.part.tokens` token 统计。
- 遥测保存到 `state.json` 的 `sessionId`、`sessionMode`（`new`/`resume`）、`lastEventAt`、`tokens` 字段；字段缺失时允许为 `null`。
- 同一任务后续 attempt 若已有 `sessionId`，使用 `codearts run --session <id>` 续跑，不默认 fork；session ID 只接受 `^[A-Za-z0-9_-]+$`。
- `Set-State` 基于旧 state 合并更新，不会因最终状态写入而丢失已记录的会话和遥测字段；旧版 state 文件无需迁移即可读取。
- 整改/恢复任务必须获得原始 TASK 和相关 FIX 的完整最小上下文：Runner 在 prompt 中列出 inbox 中全部指令文件，以最后一份为准但要求 Worker 结合前置背景。
- `local`、`ssh-shell`、`ssh`、`remote-worktree` 使用一致的会话语义；远端 shell 参数通过 `Quote-Posix` 安全引用，session ID 校验后再拼入命令。

## 四 Worker 派发（v1.2）

- `bridge.ps1 dispatch` 一次性最多派发 4 个不同 worker 的任务，默认 `MaxWorkers = 4`。
- 非阻塞启动子 PowerShell 进程执行 `run -TaskId`，默认打开独立 PowerShell 窗口显示心跳和事件摘要；`-Quiet` 才隐藏窗口。使用全局 `dispatcher.lock` 文件锁防止重复领取。
- 派发前原子地把任务置为 `QUEUED`；`run` 接受 `QUEUED`。活跃数统计 `QUEUED`、`STARTING`、`RUNNING`，不得超过 `MaxWorkers`。
- 候选状态仅限 `READY`、`FIX_REQUIRED`、`RETRYABLE`；不会自动重跑 `BLOCKED`、`FAILED`、`AUTH_REQUIRED`。
- 同一远端工作区仍只允许一个写任务；同一源码通过四个独立 `remote-worktree` 项目和四台主机并行，不共享任务工作区。
- 派发失败时恢复任务原状态并记录明确错误，不留下永久 `QUEUED`。
- `runtime/logs/dispatcher/` 存放派发摘要 JSON；Worker stdout/stderr 写入 `runtime/logs/<task-id>.attempt-NNN.stdout.log` 和 `.stderr.log`。
### 可见窗口行为

- 默认派发打开独立 PowerShell 小黑窗，显示任务/项目/attempt/session/pid/elapsed 心跳（每5秒），心跳含 `events=`/`思考=`/`工具=` 三个累计计数（已处理的 stdout 事件、thinking/reasoning 摘要、tool_use 摘要行数），以及逐行公开事件摘要（事件类型、工具名、公开文本）。
- 思考块（reasoning/thinking）以 `[思考]` 前缀公开显示正文，与普通公开文本同样经过敏感信息遮盖（AK/SK/Bearer/password/token/secret/api_key → `***`）和 160 字单行截断；`--thinking` 已默认启用（`New-WorkerRunArguments` 统一附加）。Worker prompt 默认要求 reasoning、工具摘要、控制台事件文本与正式交付全部使用纯英文 ASCII，避免中文、智能引号、长破折号等非 ASCII 字符经过控制台传输后乱码。无法提取正文时显示 `[思考] type=<type>`。完整原始 stdout/stderr 保留在本地 attempt 日志。
- 结束时无论 `REVIEW_REQUIRED` 还是 FAILED/BLOCKED/AUTH_REQUIRED/RETRYABLE/CANCELLED，都先把 outbox 的 `RESULT.md`（最多前 20 行）和 `TESTS.md`（最多前 15 行）摘要直接打进窗口（经敏感信息遮盖），再打印现有状态行；outbox 完全为空时打印「outbox 为空，无结果可显示」。所有最终状态都会保留 10 秒供查看，随后自动关闭窗口。
- `-Quiet` 隐藏窗口并压制控制台进度，但不影响日志落盘和遥测解析。

### 任务启动回显约定

- 后续新任务默认启用回显。手动执行 `dispatch` 或 `run` 时不要附加 `-Quiet`；Windows 会显示独立窗口，Linux 前台终端会显示心跳、思考和工具摘要。
- systemd 守护进程仍使用 `-Quiet`，避免后台子进程占住调度管道；任务启动后由架构师使用脱敏回显脚本查看事件，不直接展示原始 JSONL：

```bash
# 当前摘要
pwsh -NoProfile -File ~/codex-glm-bridge-repo/scripts/show-progress.ps1 -TaskId <task-id>

# 持续回显；Ctrl+C 退出，不会中断 Worker
pwsh -NoProfile -File ~/codex-glm-bridge-repo/scripts/show-progress.ps1 -TaskId <task-id> -Follow
```

- `show-progress.ps1` 复用 Bridge 的敏感信息遮盖和单行截断规则。架构师只回显公开事件摘要，验收仍以 `RESULT.md`、`DIFF.stat`、`TESTS.md` 和必要 diff 为准。
- Windows 独立回显窗口不要使用 `pwsh -NoExit` 启动；任务输出结束后保留 10 秒并自动关闭。

- `-DryRun` 无副作用模式只输出调度决策，不启动 CodeArts，供测试验证。
- 并行开发必须使用独立 `remote-worktree` 工作区；`existing` 模式仍不能让多个任务同时写同一路径。

## 入口

```powershell
# 初始化目录
pwsh -File .\scripts\bridge.ps1 bootstrap

# 检查环境
pwsh -File .\scripts\bridge.ps1 doctor

# 查看全部项目和任务
pwsh -File .\scripts\bridge.ps1 status

# 一次性派发最多四个不同项目的任务
pwsh -File .\scripts\bridge.ps1 dispatch -MaxWorkers 4

# 仅查看调度决策，不启动 Worker
pwsh -File .\scripts\bridge.ps1 dispatch -DryRun

```

完整流程见 [protocol/PROTOCOL.md](protocol/PROTOCOL.md)。

## Linux Daemon（systemd user service）

桥迁 Linux 后用 systemd user service 替代 NSSM。先确认 52 号主机可以执行 `pwsh`，并把本仓库同步到 `/home/nathan/codex-glm-bridge-repo`：

```bash
# 在 52 上创建 service unit
mkdir -p ~/.config/systemd/user
cat > ~/.config/systemd/user/codex-glm-bridge.service << 'EOF'
[Unit]
Description=codex-glm Bridge Daemon
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
WorkingDirectory=/home/nathan/codex-glm-bridge-repo
Environment=PATH=/home/nathan/.local/bin:/usr/local/bin:/usr/bin:/bin
Environment=POWERSHELL_TELEMETRY_OPTOUT=1
ExecStart=/home/nathan/.local/bin/pwsh -NoProfile -File /home/nathan/codex-glm-bridge-repo/scripts/bridge-daemon.ps1 run -MaxWorkers 4 -IntervalSeconds 10
ExecStop=/home/nathan/.local/bin/pwsh -NoProfile -File /home/nathan/codex-glm-bridge-repo/scripts/bridge-daemon.ps1 stop -ShutdownTimeoutSeconds 60
Restart=on-failure
RestartSec=5
TimeoutStopSec=75

[Install]
WantedBy=default.target
EOF

systemctl --user daemon-reload
systemctl --user enable --now codex-glm-bridge
systemctl --user status codex-glm-bridge --no-pager
pwsh -NoProfile -File ~/codex-glm-bridge-repo/scripts/bridge-daemon.ps1 status
```

日常管理：

```bash
systemctl --user start codex-glm-bridge
systemctl --user stop codex-glm-bridge
systemctl --user restart codex-glm-bridge
journalctl --user -u codex-glm-bridge -n 100 -f
```

这里启动的是调度守护进程 `bridge-daemon.ps1`，不是直接运行 `codearts run`。守护进程每轮调用 `bridge.ps1 dispatch -MaxWorkers 4 -Quiet`，4 个 `ssh` worker 再各自在自己的 Linux 主机和独立账号下执行 CodeArts CLI。

无需 root/UAC，`systemctl --user` 即可管理。

## CodeArts CLI 授权

CLI 与 CodeArts Agent IDE 的登录状态相互独立。首次运行前需按华为云官方指引配置 `CODEARTS_CLI_AK` 和 `CODEARTS_CLI_SK`；Bridge 只检查变量是否存在，不打印、记录或复制其值。

配置后重新运行 `doctor`，两个授权变量均显示 `true`，再投递 Worker 任务。
