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

新安装默认可信 LAN、auth off。若已有 `agent.env`，脚本保留现有 token 配置。

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
