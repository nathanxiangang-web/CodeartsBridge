# deploy/

当前只把这里当成“安装/升级入口”，不要从旧实验脚本猜运行架构。

## 支持的脚本

### Bridge 主机

```bash
./deploy/install-bridge.sh
```

功能：

- 创建/更新 `.venv`
- editable install
- bootstrap + doctor
- 安装/重启 `bridge.service`
- 默认运行 `bridge serve --with-pipeline`

常用覆盖：

```bash
BRIDGE_WITH_PIPELINE=0 ./deploy/install-bridge.sh
BRIDGE_PORT=8088 ./deploy/install-bridge.sh
BRIDGE_INSTALL_SYSTEMD=0 ./deploy/install-bridge.sh
```

### Worker

```bash
./deploy/install-worker-agent.sh
```

功能：

- 创建/更新 `.venv`
- editable install
- 创建 Agent 配置
- 安装/重启 `bridge-worker-agent.service`
- 检查 `/v1/health`

新安装默认可信 LAN、auth off。若已有 `agent.env`，`BRIDGE_AGENT_AUTH=auto` 会保留现有 token 配置。

CodeArts 凭据与 Agent token 分开保存：

```text
~/.config/codeartsbridge/agent.env     # BRIDGE_AGENT_TOKEN，可选
~/.config/codeartsbridge/codearts.env  # CODEARTS_CLI_AK / CODEARTS_CLI_SK
```

`codearts.env` 必须由运维人员创建并设为 `600`；安装脚本只加载和保留它，不读取或输出凭据值。

当前实验室安装时增加固定版本门禁：

```bash
BRIDGE_CODEARTS_EXPECTED_VERSION=26.8.12 ./deploy/install-worker-agent.sh
```

生成的 systemd unit 会禁用 CodeArts 自动升级，并清除可能污染运行时选择的旧 `OPENCODE_*` 环境。

如果旧安装脚本曾自动生成 token，但当前 `workers.json` 没有对应 token，请明确恢复可信 LAN 模式：

```bash
BRIDGE_AGENT_AUTH=off ./deploy/install-worker-agent.sh
```

要显式启用 token：

```bash
BRIDGE_AGENT_AUTH=token BRIDGE_AGENT_TOKEN='...' ./deploy/install-worker-agent.sh
```

## CodeArts 运行时核查与修复

部署后只读核查：

```bash
python3 deploy/codearts-worker-runtime.py audit \
  --expected-version 26.8.12 \
  --require-aksk
```

权限修复默认只预览，必须显式 `--apply`：

```bash
python3 deploy/codearts-worker-runtime.py fix-permissions
python3 deploy/codearts-worker-runtime.py fix-permissions --apply
```

完整根因、备份、回滚和真实 write 验收见 `docs/CODEARTS-WRITE-PERMISSION-RUNBOOK.md`。

## Reference unit

`bridge-worker-agent.service` 是当前实验室路径的参考 unit。正常部署优先使用安装脚本，因为脚本会按当前用户和仓库路径生成 systemd unit。

## 更新

Bridge：

```bash
git pull --ff-only
./deploy/install-bridge.sh
```

Worker：

```bash
git pull --ff-only
./deploy/install-worker-agent.sh
```

完整运行手册见 `docs/USAGE.md`。
