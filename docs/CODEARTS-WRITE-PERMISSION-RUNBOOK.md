# CodeArts built-in write/edit 排查与恢复手册

> 状态：已在 2026-09-20 的四台 Worker 上完成复现、修复和真实 Agent 验收。
>
> 适用基线：CodeArts CLI `26.8.12`、Linux x64、Agent HTTP transport。

## 1. 结论

Issue #38 的 built-in `write/edit` 失败不是 Linux 文件所有权问题，也不是已确认的 CodeArts CLI 固有缺陷。现场存在两个叠加问题：

1. 检查和修改了未被当前 CLI 使用的影子权限文件；真实权限仍是 `ask`。
2. 长期运行的 Agent 继承了远程开发终端的旧 `OPENCODE_*` 环境，导致子进程再次切回旧配置。

修复真实权限文件并从干净环境重启 Agent 后，以下矩阵全部通过：

| 场景 | 结果 |
|---|---|
| 项目内、默认 Agent | 原生 `write` 成功 |
| 项目内、显式 Build | 原生 `write` 成功 |
| 项目外、显式 Build | 原生 `write` 成功 |
| 默认 Agent + `--auto` | 原生 `write` 成功 |
| Agent HTTP 真实 Job | `COMPLETED`、exit `0`、出现原生 `write` 事件 |

因此 Bridge 未显式传 `--agent build` 不是本次根因。`debug config` 已确认默认 Agent 是 `build`，受控对照也证明默认 Agent 可以成功写入。

## 2. 关键证据

### 2.1 失败基线

失败时，项目内目标文件由 built-in `write` 触发：

```text
permission requested: edit (...); auto-rejecting
The user rejected permission to use this specific tool call.
```

文件未创建，保护超时退出。这个结果排除了普通 Unix 所有权和目录可写性问题。

### 2.2 CLI 实际使用的数据目录

不要根据文件名猜配置位置，始终先执行：

```bash
codearts debug paths
```

现场 `26.8.12` 返回：

```text
data  /home/nathan/.local/share/opencode
```

所以真实权限文件是：

```text
/home/nathan/.local/share/opencode/storage/permission/global.json
```

以下同名文件当时都不是该进程的生效源：

```text
~/.codeartsdoer/cli-data/storage/permission/global.json
~/.codeartsdoer/codearts-data/storage/permission/global.json
```

失败时，真实文件中的以下权限均为 `ask`：

```text
edit
write
external_directory_write
dotfile
```

CLI 非交互运行会自动拒绝 `ask`，因此“磁盘上另一个 global.json 已是 allow”不能证明最终配置正确。

### 2.3 Agent 旧环境污染

权限修复后，手工 CLI 已成功，但旧 Agent HTTP Job 仍在 reasoning 后、tool event 前挂起。进程环境检查发现旧 Agent 带有：

```text
OPENCODE_CONFIG=/home/nathan/.codeartsdoer/codearts-data/codearts.json
OPENCODE_*
```

新 SSH 登录 shell 没有这些变量。清除全部 `OPENCODE_*` 并重启 Agent 后，同一 HTTP 链路在约 30 秒内完成，事件中出现：

```text
tool=write
status=completed
executeResult=succeed
exitCode=0
```

## 3. 部署前只读核查

从新的 SSH 登录 shell 执行：

```bash
python3 deploy/codearts-worker-runtime.py audit \
  --expected-version 26.8.12 \
  --require-aksk
```

通过标准：

```text
PASS version=26.8.12
PASS data_dir=...
PASS permission.edit=allow
PASS permission.write=allow
PASS permission.external_directory_write=allow
PASS permission.dotfile=allow
PASS stale_opencode_env=none
PASS auto_update=disabled
PASS agent_aksk=present
PASS agent_health=ok
RESULT PASS
```

该命令只读取配置和进程环境，只输出敏感变量是否存在，不输出 AK/SK、token 或密码值。

Agent 尚未启动时可做配置预检：

```bash
python3 deploy/codearts-worker-runtime.py audit \
  --expected-version 26.8.12 \
  --skip-agent
```

## 4. 权限修复

先预览，不写文件：

```bash
python3 deploy/codearts-worker-runtime.py fix-permissions
```

确认 `permission_file` 来自 `codearts debug paths` 返回的 data 目录后，再显式应用：

```bash
python3 deploy/codearts-worker-runtime.py fix-permissions --apply
```

工具只处理：

```text
edit
write
external_directory_write
dotfile
```

应用前会在同目录创建 UTC 时间戳备份：

```text
global.json.before-codeartsbridge-write-fix-YYYYmmddTHHMMSSZ
```

它不会修改浏览器、联网、bash、凭据或其他权限。

回滚时停止新任务，将备份复制回 `global.json`，再重启 Agent 并重新运行 audit。

## 5. 干净 Agent 环境

systemd 部署使用两个独立环境文件：

```text
~/.config/codeartsbridge/agent.env     # Agent HTTP token，可选
~/.config/codeartsbridge/codearts.env  # CodeArts AK/SK
```

`codearts.env` 示例只包含变量名，实际值不要写入仓库：

```text
CODEARTS_CLI_AK=...
CODEARTS_CLI_SK=...
```

权限必须是：

```bash
chmod 600 ~/.config/codeartsbridge/codearts.env
```

安装器生成的 unit 会：

- 加载独立的 `codearts.env`；
- 设置 `CODEARTS_DISABLE_AUTO_UPDATE=true`；
- 清除已知 `OPENCODE_*` 变量；
- 可通过 `BRIDGE_CODEARTS_EXPECTED_VERSION=26.8.12` 拒绝错误版本。

安装示例：

```bash
BRIDGE_CODEARTS_EXPECTED_VERSION=26.8.12 \
  ./deploy/install-worker-agent.sh
```

## 6. 真实写入验收

只读 audit 通过后，还必须运行一个受限真实任务。验收 prompt 应明确：

```text
Use the built-in write tool only.
Do not use bash, Python, base64, cp, shell redirection, or any shell fallback.
Create one dedicated probe file with exact content.
If built-in write is rejected, stop and report the rejection.
```

同时检查：

1. Job 状态为 `COMPLETED`。
2. exit code 为 `0`。
3. 事件或 session log 中存在 `tool=write`。
4. tool state 为 `completed`、`executeResult=succeed`。
5. 目标文件内容逐字一致。
6. 验收后删除专用探针文件。

不能用以下现象替代原生 write 验收：

```text
python3 -c
base64 decode
shell redirection
仅检查 exit 0
```

shell fallback 仍可作为任务级应急路径，但不能再被描述为 built-in write 已解决的证据。

## 7. 版本问题必须分开

本报告只解决 `26.8.12` 的运行时配置问题。

`26.9.7` 在当前账号上于 Model Queuing 阶段被 package/account gate 拒绝，发生在任何 write 工具调用前。它与本报告的权限根因相互独立。生产 Worker 继续遵循 `docs/CODEARTS-PINNED-RUNTIME.md` 的固定版本规则。

## 8. 快速判定表

| 现象 | 优先检查 |
|---|---|
| `permission requested: edit ... auto-rejecting` | `codearts debug paths` 和真实 `global.json` |
| 手工 CLI 成功、Agent Job 在 tool 前挂起 | Agent 进程中的 `OPENCODE_*` |
| 模型队列直接 Access denied | 版本与账号路由，不是 write 权限 |
| audit 通过但真实 Job 失败 | Job session/stderr、模型队列、精确启动参数 |
| fallback 能写但没有 write 事件 | 仍未完成原生 write 验收 |
