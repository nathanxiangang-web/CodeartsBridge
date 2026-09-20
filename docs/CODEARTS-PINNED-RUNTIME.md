# CodeArts CLI 固定运行时 — 26.8.12

> 当前实验室 Worker 的 CodeArts CLI 不是“跟随最新版本”的普通依赖，而是 **固定版本运行时**。
>
> 当前唯一已验证可用版本：`26.8.12`。

## 1. 为什么固定在 26.8.12

现场已确认：

```text
26.8.12
→ 现有实验室账号可以正常进入 huaweicloud-maas/GLM-5.2
→ Bridge / Agent 可以实际执行任务

26.9.7
→ 客户端安装本身成功
→ 在 Model Queuing 阶段被服务端拒绝
→ 发生在任何 write/edit 工具调用之前
```

因此：

```text
26.9.7 的 Access denied / package gate
≠ Bridge 故障
≠ outbox 故障
≠ built-in write/edit 故障
```

在华为账号路由/套餐兼容问题没有明确解决前，生产 Worker **禁止升级到 26.9.x 或其他未知版本**。

## 2. 已归档的恢复包

GitHub Release：

```text
tag:
codearts-cli-26.8.12-pinned

name:
CodeArts CLI 26.8.12 (Pinned Linux x64)
```

资产：

```text
codearts-install-26.8.12-linux-x64.tar.gz
codearts-install-26.8.12-linux-x64.tar.gz.sha256
```

Release 页面：

```text
https://github.com/nathanxiangang-web/CodeartsBridge/releases/tag/codearts-cli-26.8.12-pinned
```

已记录 SHA-256：

```text
5ab25bff375ba0027757d4cb46f46c22b32cc7df9973ca75d2a86ff8aa3a0b67
```

这个包用于恢复 Worker，不要把二进制本体提交到 Git tree。

## 3. 恢复安装

下载两个 Release asset 后：

```bash
sha256sum -c codearts-install-26.8.12-linux-x64.tar.gz.sha256

tmp_dir="$(mktemp -d)"
tar -xzf codearts-install-26.8.12-linux-x64.tar.gz -C "$tmp_dir"

mkdir -p ~/.codeartsdoer/installers/bin

install -m 711 "$tmp_dir/agentkernel"   ~/.codeartsdoer/installers/bin/codearts

install -m 711 "$tmp_dir/codearts"   ~/.codeartsdoer/installers/codearts

~/.codeartsdoer/installers/bin/codearts --version
```

期望输出必须是：

```text
26.8.12
```

如果不是 26.8.12，不要启动 Worker Agent。

恢复只替换 CLI 二进制。保留现有：

```text
~/.codeartsdoer/cli-data/
~/.config/codeartsbridge/
```

不要把 AK/SK、token、permission 配置提交到仓库。

## 4. 运行规则

当前 Worker 版本策略：

```text
生产 / 日常任务
→ 26.8.12

新版本测试
→ 单独一台测试机
→ 不直接覆盖四台 Worker
→ 通过账号路由 + 真实任务验收后才允许升级
```

禁止在生产 Worker 执行：

```bash
codearts upgrade
```

也不要让安装脚本自动追最新 CodeArts。

Bridge 自身可以升级；CodeArts CLI 版本升级是另一件事。

## 5. Bridge 当前如何找到 CodeArts

当前 Agent runner 支持显式 `cliPath`，也支持默认查找。

如果 Worker 配置没有 `cliPath`，正常会命中：

```text
~/.codeartsdoer/installers/bin/codearts
```

因此目前最简单的生产约束是：

```text
该路径必须保持 26.8.12
```

后续可以进一步收紧为：

```json
{
  "id": "w01",
  "transport": "agent",
  "endpoint": "http://192.168.178.52:8765",
  "cliPath": "/home/nathan/.codeartsdoer/installers/bin/codearts",
  "enabled": true
}
```

并增加版本门禁：

```text
expected 26.8.12
actual != 26.8.12
→ Worker 拒绝启动任务
```

在版本门禁真正实现前，不要在文档中把它描述成已完成能力。

## 6. 升级策略

以后看到 CodeArts 提示新版本时：

1. 不在四台 Worker 上直接升级。
2. 记录新版本号。
3. 在独立测试 Worker 安装。
4. 先跑最小原生验证：
   - `codearts --version`
   - 模型能进入 Model Queuing / 生成
   - `codearts run --format json`
5. 再跑 Bridge 真实任务。
6. 验证账号兼容、事件流、outbox、artifact。
7. 全部通过后才修改本文件的 pinned version。

## 7. 与 built-in write/edit 问题的关系

必须分开：

```text
A. 26.9.7 package/account routing 问题
→ 任务在模型队列阶段就失败

B. 26.8.12 built-in write/edit 问题
→ 模型已经运行
→ 工具调用时可能立即拒绝
→ shell/python fallback 可以写正式成果
```

不要把 A 和 B 混成一个问题。

当前仍需要继续调查 B，但调查必须基于 **26.8.12 pinned runtime**，否则版本变量会污染结论。

## 8. 给 Coding Agent 的结论

看到本仓库时默认假设：

```text
CodeArts CLI = vendor-pinned 26.8.12
Do not upgrade.
Do not replace with latest.
Do not diagnose 26.9.7 package denial as a Bridge bug.
```

需要变更 CodeArts 版本时，先更新本文件和真实验收证据。
