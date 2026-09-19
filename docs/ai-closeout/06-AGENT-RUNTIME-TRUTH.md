# 06 — Agent Runtime Truth：outbox 与 UI 忙闲收口

> 这是给下一位 Coding Agent 的直接执行文档。  
> 当前目标不是继续扩架构，而是把 **Agent 已经成为主运行时** 这件事贯彻到底。  
> 请新建小分支：`fix/agent-runtime-truth`。

## 0. 现场已经确认

当前 Worker 已经通过 Agent 执行 CodeArts，实时 reasoning/tool 回显也已跑通。

但现场仍有两个明显的“旧世界残留”：

### 问题 A：Agent outbox 在 CodeArts projectRoot 之外

当前 `src/bridge/agent/runner.py`：

```python
outbox_path = job_dir / "artifacts" / "outbox"
env["CODEARTS_OUTBOX"] = str(outbox_path)

subprocess.Popen(
    ...,
    cwd=job.projectRoot,
)
```

因此实际形成：

```
CodeArts 工作区
/home/nathan/bridge-python

Agent outbox
/home/nathan/.codex-glm-bridge/agent/jobs/<job>/artifacts/outbox
```

CodeArts 内置 `write/edit` 对 projectRoot 外路径会拒绝写入。

现场已经出现：

```
write RESULT.md
-> rejected

模型被迫改用：
bash
python open(...)
cp
base64
```

这说明 Agent 虽然接通了，但交付目录没有真正 Agent-local / project-local 化。

---

### 问题 B：UI 忙闲仍主要相信 Bridge task state

当前 `src/bridge/web/js/pages/thinking.js` 通过：

```
RUNNING
STARTING
QUEUED
```

筛选任务，再决定某 Worker 是否显示“思考中”。

现场出现：

```
Worker 顶部：空闲
下面日志：CodeArts 还在继续 bash / write / tool
```

说明：

```
Agent Job 仍 RUNNING
但 Bridge task state 暂时没有被 UI 识别为 active
```

UI 因此产生“进程还在跑，但显示空闲”的假状态。

既然 Agent 已经是主运行时：

> **进程是否忙，应优先相信 Agent Job；任务业务状态继续由 Bridge state 表示。**

---

# 1. 本 PR 只解决这两个问题

不要顺手继续重构 scheduler / review / supervision / CLI。

目标文件优先限定：

```
src/bridge/agent/runner.py
src/bridge/agent/artifacts.py
src/bridge/agent/server.py        # 仅在需要暴露 job runtime 时
src/bridge/api/server.py          # 仅在需要聚合 Agent runtime 时
src/bridge/web/js/pages/thinking.js
相关 tests
```

如无必要，不新增新模块。

---

# 2. 修复 A：给 CodeArts 一个 project-local writable outbox

## 推荐目标结构

CodeArts 执行时：

```
<projectRoot>/
└── .codeartsbridge/
    └── outbox/
        └── <jobId>/
            ├── RESULT.md
            ├── TESTS.md
            ├── DIFF.stat
            └── DIFF.patch
```

也就是：

```
CODEARTS_OUTBOX
=
<projectRoot>/.codeartsbridge/outbox/<jobId>
```

必须满足：

1. 路径在 `projectRoot` 以内。
2. CodeArts 内置 `write/edit` 能直接写。
3. 不要求模型再用 bash/python/cp 绕过编辑器。
4. Job 完成后，Agent 把这些文件复制/归档到：

```
agent/jobs/<jobId>/artifacts/outbox
```

5. Bridge 仍然通过现有 artifact API 拉回 `task/outbox`。
6. 临时 project-local outbox 在成功归档后清理。
7. 清理失败不能导致任务成果丢失；先归档、后清理。

---

## Git 污染处理

不要修改项目的 tracked `.gitignore`，避免 Worker PR 出现额外噪声。

优先使用：

```
.git/info/exclude
```

加入：

```
.codeartsbridge/
```

要求：

- 重复执行幂等。
- 非 git 项目时不要报错。
- 不为此引入新的“workspace policy”层。

---

## 不要这样做

不要：

- 放宽 CodeArts 自己的 write 安全边界。
- 让模型继续依赖 `bash cp` 作为正式交付方式。
- 把 Agent 私有 job 目录挂载/软链成复杂新抽象。
- 再引入一套 artifact service。
- 改 WORKER prompt 去“教模型绕过 write”。

正确修复是**把目标目录放到正确的位置**。

---

# 3. 修复 B：UI 忙闲以 Agent Job runtime 为事实来源

## 当前错误语义

现在 roughly：

```
Bridge task state == RUNNING/STARTING/QUEUED
  -> Worker busy
else
  -> Worker idle
```

这会产生：

```
Agent Job RUNNING
Bridge task 暂时不是 active state
UI = 空闲
```

---

## 目标语义

UI 的 Worker 头部应区分两个维度：

### 运行时维度

由 Agent Job 决定：

```
RUNNING / STARTING
-> Worker 忙

没有 active Agent Job
-> Worker 空闲
```

### 任务业务维度

由 Bridge task state 决定：

```
REVIEW_REQUIRED
APPROVED
INTEGRATING
DONE
FAILED
...
```

不要拿业务状态替代“进程到底还在不在跑”。

---

## 推荐实现方式

优先最小改动，不新增轮询体系。

可选方案按优先级：

### 方案 1（优先）

扩展现有 Worker/API runtime 数据，让 `/api/workers` 返回真实 Agent runtime：

```json
{
  "id": "w01",
  "runtimeState": "busy",
  "currentTasks": [
    {
      "taskId": "...",
      "jobId": "...",
      "jobState": "RUNNING"
    }
  ]
}
```

`thinking.js` 直接使用这个 runtime 事实。

### 方案 2

如果现有 inflight 数据已经足够，则 Bridge 根据：

```
task/inflight.json
-> endpoint
-> jobId
-> Agent /v1/jobs/<jobId>
```

聚合到 `/api/workers`。

不要让浏览器自己直接访问 4 台 Agent。

---

## UI 要求

当 Agent 仍 RUNNING：

```
顶部必须显示：思考中 / 运行中
```

即使 Bridge task 已经临时进入：

```
REVIEW_REQUIRED
APPROVED
其它非 active state
```

也不能在 Agent 进程仍活着时显示“空闲”。

当 Agent Job 终止后：

```
COMPLETED
ASSISTANCE_REQUIRED
TIMED_OUT
CANCELLED
```

才允许 Worker runtime 显示空闲。

历史日志可以继续留在窗口里，但顶部状态必须反映真实 runtime。

---

# 4. 真实验收

## Scenario A — project-local outbox

创建最小任务，让 Worker 明确执行：

```
write RESULT.md
write TESTS.md
write DIFF.stat
```

验收：

```
内置 write 成功
没有 "write tool was rejected"
没有为了交付再走 python/cp/base64
CODEARTS_OUTBOX 位于 projectRoot/.codeartsbridge/...
Agent artifacts/outbox 最终有对应文件
Bridge task/outbox 最终有对应文件
```

---

## Scenario B — Git cleanliness

任务开始前：

```
git status --short
```

任务结束并完成 artifact 归档/清理后再次执行。

要求：

```
.codeartsbridge/
```

不出现在 git status。

---

## Scenario C — runtime busy truth

让一个 Agent Job 持续运行 2~3 分钟。

期间人为让 Bridge task state 进入一个当前 UI 不认为 active 的状态，或使用能复现现场竞态的真实流程。

要求：

```
Agent Job RUNNING
=> UI 顶部绝不能显示“空闲”
```

---

## Scenario D — runtime end

Agent Job 真正结束后：

```
UI 顶部 -> 空闲
```

历史日志允许保留。

---

# 5. 测试要求

至少新增以下回归：

```
test_agent_outbox_is_inside_project_root
test_agent_archives_project_local_outbox
test_agent_outbox_cleanup_is_post_archive
test_project_local_outbox_is_git_excluded
test_worker_runtime_busy_comes_from_active_agent_job
test_thinking_ui_does_not_show_idle_for_running_agent_job
```

名字可调整，但语义不能少。

不要只测字符串存在。

至少一个测试必须验证：

```
projectRoot
-> CodeArts 写文件
-> Agent archive
-> Bridge fetch
```

中的真实文件搬运行为。

---

# 6. PR 完成时必须回答

PR 描述必须明确：

```
1. CODEARTS_OUTBOX 最终在哪里？
2. CodeArts 内置 write 是否能直接写？
3. Agent 私有 artifact 目录何时归档？
4. project-local 临时目录何时清理？
5. Worker busy/idle 最终相信谁？
6. Agent Job RUNNING 但 Bridge state 非 RUNNING 时 UI 显示什么？
```

回答不出来，不要合并。

---

# 7. 不要碰的范围

本 PR 不处理：

```
PR #33 dispatch 收口
PR #34 policy/runtime 删除
PR #35 task display clear
Review/Integration 生命周期
MCP
adaptive/cost
大规模 README 重写
```

保持这个 PR 小而真实。

目标不是“再做一套 Agent Runtime”，而是：

> **既然已经用 Agent，就让 outbox、busy/idle、回显这三件事都以 Agent 的真实运行事实为准。**
