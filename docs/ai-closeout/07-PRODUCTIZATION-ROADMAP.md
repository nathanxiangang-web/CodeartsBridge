# 07 — 收口后产品化路线图

审计基线：`main@59ca2e709cad3e03fdad50cdb53c8d0fd2556314`

## 0. 当前阶段判断

CodeartsBridge 已经完成核心运行链收口，当前不再以“继续重构架构”为目标，而进入：

```
收口尾声
→ 日常可用
→ UI / 可观察性 / 使用效率
```

已经成立并应冻结的主链：

```
Task
→ auto_dispatch + scheduler
→ Worker Agent
→ CodeArts CLI
→ reasoning/tool/event 回显
→ outbox archive
→ Bridge fetch
→ REVIEW_REQUIRED
→ APPROVED
→ real integration
→ DONE + integratedSha
```

Issue #38 已关闭。CodeArts `--format json` 下 built-in write/edit 仍可能立即拒绝，这是 CLI 限制；当前 bash fallback 是已验证的正式成果写入路径。不要再次围绕该限制重做 Agent/outbox 架构。

PR #35 已合入 main。任务页现在已有：

```
清除已结束
恢复隐藏 (N)
```

实现只使用浏览器 localStorage，不删除 task，不修改 state，不产生控制面写操作。

---

## 1. P0 — 清掉“已经删除模块留下的死契约”

最新 closeout 已物理删除：

```
supervision/
policy/
runtime/
dispatch.py
daemon.py
adaptive.py
cost.py
```

但当前代码仍有残留入口：

```
src/bridge/cli.py
  adaptive-dispatch
  cost

pyproject.toml
  bridge-daemon = "bridge.daemon:main"
```

这些入口会指向已经不存在的模块。

### 要做

1. 从 CLI parser / COMMAND_MAP / handler 中删除 `adaptive-dispatch` 和 `cost`。
2. 从 `pyproject.toml` 删除 `bridge-daemon` entry point。
3. 全仓搜索已删除模块的 import / 文档引用。
4. 增加 CLI contract regression：
   - `bridge --help` 正常。
   - help 中暴露的每个命令都必须有真实可导入 handler。
   - packaging entry point 不允许指向不存在模块。

### 完成标准

```
pytest 全绿
Python 3.11 / 3.12 / 3.13 CI 全绿
bridge --help 不出现死亡命令
pip install 后不存在 bridge-daemon 死入口
```

这是一轮纯减法，不允许顺手增加替代架构。

---

## 2. P1 — UI 正式进入主开发阶段

Agent / Scheduler / Lifecycle / Integration 主架构冻结。没有真实 field bug，不再改底层。

### 2.1 先验证 PR #35 线上生效

main 已包含按钮代码。如果现场页面仍看不到按钮，先验证部署，而不是再改 UI：

```
git rev-parse HEAD
# 应至少包含 59ca2e7

curl http://<bridge-host>:8080/js/pages/tasks.js | grep task-clear-finished
```

服务端对未 hash 的 JS 返回 `Cache-Control: no-cache`，所以源码已更新但浏览器仍没有按钮时，优先检查：

```
运行中的 Bridge 是否指向最新 checkout
部署目录是否 pull 到最新 main
浏览器是否仍持有旧页面实例
```

不要重复实现第二套“清除任务”。

### 2.2 Tasks 页面

保持 read-only，重点提高每天使用效率：

- 活跃任务优先，已结束任务靠后。
- 状态筛选覆盖当前真实状态，不只 RUNNING/DONE/FAILED。
- 增加更新时间 / 执行耗时等已有数据展示。
- 隐藏数量、恢复隐藏语义保持简单。
- 不增加真正删除 task 的按钮。

### 2.3 Task Detail

这是下一阶段 UI 最高价值页面。

应直接展示已有真实数据：

```
worker / project
state + message
attempt
elapsed
lastEventAt
RESULT.md
TESTS.md
DIFF.stat
COMMIT.sha
integratedSha
integration failure / worker failure
最近事件
```

目标是：出现失败时，用户尽量不需要 SSH 到 Worker 才知道发生了什么。

### 2.4 Thinking

必须区分：

```
正在实时运行
vs
Worker 已空闲，但保留上一任务历史日志
```

不要再让“保留历史输出”视觉上看起来像 Agent 仍在运行。

继续保留：

- 动态 Worker slot。
- 120 行 DOM 上限。
- 手动滚动不被强制拉到底。
- Agent Job runtime 作为 busy/idle 真相之一。

### 2.5 Overview

只做高价值状态：

```
Worker online/offline
busy/idle
current task
elapsed
last event
任务状态计数
```

不要恢复重控制台、项目设置、Worker 设置、Review 操作按钮。

---

## 3. P2 — 最后一次控制循环收口

这项排在 UI 第一阶段之后，不要抢跑。

当前真实情况仍是：

```
bridge serve
  → API / UI / MCP

bridge pipeline
  → architect review
  → auto_dispatch
  → integrate
  → conflict
```

所以“单一长期运行进程”目标尚未真正完成。

### 目标

最终如果要自治运行，应只有：

```
bridge serve
├── API / UI
└── 一个 TaskLoop
    ├── review
    ├── dispatch
    └── integrate
```

约束：

1. 必须复用现有 `run_pipeline_cycle` / `auto_dispatch` / `integrate_loop`，不能新造第四套 loop。
2. Agent Watchdog 仍是 Worker 进程唯一生命周期 owner。
3. 不把 UI 变成第二控制平面。
4. 在自动化前，先跑真实 Scenario A/B/G。
5. 如果现阶段人工 `dispatch/review/integrate` 更适合实际使用，也可以暂时保留手动模式；不要为了“形式上的单进程”引入新故障。

完成这项后，再决定是否删除独立 `bridge pipeline` 长期运行模式。

---

## 4. P2 — 删除 Integration 遗留平行实现

当前 canonical integration 是：

```
src/bridge/integration.py::integrate_task
```

它负责：

```
APPROVED
→ INTEGRATING
→ cherry-pick
→ verify
→ INTEGRATED
→ integratedSha
→ DONE
```

但仍存在：

```
src/bridge/application/integration_service.py::integrate_approved_task
```

以及 `integration.py` 中若干 legacy merge helpers。

### 要做

先做全仓引用审计。

如果没有生产调用：

- 删除 `application/integration_service.py`。
- 删除只为它保留的 legacy integration helpers。
- 保留一个 canonical integration 路径。
- 不做长期 wrapper 兼容。

如果仍有真实调用，则改成委托 canonical `integrate_task`，禁止维护两套状态语义。

---

## 5. P3 — 文档与部署真相

在 P0/P1 完成后统一更新：

```
README.md
docs/ai-closeout/README.md
NEXT.md
部署说明
```

必须删除已经不存在的：

```
dispatch.py
bridge-daemon
policy/runtime/supervision
adaptive/cost
旧 Agent outbox 问题
```

并明确：

```
Agent 是保留的核心运行时
bash fallback 是当前 CodeArts JSON 模式的正式写成果路径
Web UI 仍是 read-only
PR #35 的“清除已结束”仅隐藏本浏览器显示
```

---

## 6. 推荐执行波次

### Wave A — 现在就做，可并行

```
Worker A
P0 CLI / packaging 死入口清理

Worker B
UI Tasks + Task Detail 第一轮

Worker C
Thinking/Overview 可观察性审查与小修

Worker D
真实验收 + 文档真相审计，不碰核心架构
```

注意避免多个 Worker 同时修改同一个文件。

### Wave B — Wave A 稳定后

```
1. 单一 TaskLoop 是否并入 bridge serve
2. 删除 integration_service / legacy integration
3. 更新 README / deploy truth
```

---

## 7. Do Not Touch

没有真实 field evidence 时，不要改：

```
src/bridge/agent/*
src/bridge/scheduler/*
主 lifecycle 状态机
artifact archive/fetch 顺序
```

不要恢复：

```
policy
supervision
第二套 runtime supervisor
adaptive scheduler
cost control layer
bridge-daemon
多 transport 兼容架构
重型 UI control plane
```

不要再次尝试通过大改 outbox 解决 CodeArts built-in write/edit 限制。

---

## 8. 下一阶段完成标准

下一阶段不是用“又增加了多少模块”衡量，而是：

```
CI 全绿
CLI 没有死亡入口
UI 能直接看清任务/Worker/成果/错误
4 Worker 连续运行稳定
任务从 create 到 DONE 的真实路径没有平行实现
日常使用不需要频繁 SSH 排障
```

做到这里后，项目应进入普通功能迭代，而不是继续架构收口。
