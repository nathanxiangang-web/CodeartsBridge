# 08 — Task 删除语义

审计基线：`main@7a63191b123ef599109ed8d388383e3f73090f6d`

## 0. 需求纠正

之前把“删除任务”误解成“只从浏览器隐藏已结束任务”。

真正需求是：

```
用户可以在 UI 删除任务。
如果任务正在运行，删除动作不能取消正在执行的 CodeArts / Agent Job。
```

因此：

```
Delete != Cancel
```

删除是任务记录/历史的清理语义，不是执行控制语义。

PR #35 当前的 localStorage 隐藏只能算临时显示功能，不能视为“任务删除”需求已完成。

---

## 1. 正确行为

### 1.1 已结束 / 无活动执行的任务

用户点击删除后：

```
UI 发真实删除请求
→ Bridge 删除该 task 的持久化记录与任务目录
→ 从任务列表消失
```

可清理内容至少包括：

```
tasks/<taskId>/
runtime/assignments/<taskId>（若存在）
对应 lease / 临时运行记录（若已失效）
```

不得影响项目代码仓库本身已经存在的提交或文件。

### 1.2 正在运行的任务

如果任务存在真实活动执行，例如：

```
STARTING
RUNNING
VERIFYING
或存在 inflight.json / 活动 assignment
```

点击删除时：

```
不调用 cancel
不调用 Agent cancel API
不 kill CodeArts
不改变远端 Job 的执行
```

但 UI 应立即把它视为“已删除”，不再出现在普通任务列表。

Bridge 不能立刻物理删除 `tasks/<taskId>`，因为当前 Worker / AgentTransport 在任务结束后仍需要这个目录：

```
fetch artifacts
clear inflight
写最终 state
释放 assignment / lease
```

因此运行中的删除必须采用：

```
delete requested
→ UI/API 隐藏
→ 运行继续
→ Worker 自然结束
→ Bridge 完成必要收尾
→ 自动物理删除 task 数据
```

这叫 deferred delete，不是 cancel。

---

## 2. 建议实现

不要把 delete 塞进状态机，不新增 `DELETING` / `DELETED` 生命周期状态。

删除属于管理元数据，不属于任务执行状态。

建议使用一个很小的 marker：

```
tasks/<taskId>/.delete-requested
```

或等价的 runtime tombstone。

### API

增加：

```
DELETE /api/tasks/<taskId>
```

返回语义：

```
200 {"deleted": true}
```

表示已立即物理删除。

或：

```
202 {"deleted": false, "pending": true}
```

表示任务仍在执行，已进入 deferred delete。

不要复用：

```
POST /api/tasks/<taskId>/cancel
```

### UI

Tasks / Task Detail 增加“删除”动作。

删除确认文案必须明确：

```
删除任务记录不会取消正在运行的 Worker。
正在运行的任务会继续执行，结束后自动清理记录。
```

运行任务不能把按钮写成“取消并删除”。

---

## 3. 删除判定

是否可以立即物理删除，不只看 state。

优先判断真实 runtime：

```
inflight.json 存在
→ 一定延迟删除

活动 assignment / lease 存在
→ 延迟删除

STARTING / RUNNING / VERIFYING / INTEGRATING
→ 延迟删除
```

对于 READY / REVIEW_REQUIRED / APPROVED / FIX_REQUIRED 等当前没有真实执行进程的任务，可以删除，但删除前必须确保 scheduler / review / integration 不会再次拾取它。

最简单方式：

```
先写 delete marker
→ 所有 scanner 跳过 delete-requested task
→ 再安全删除
```

这样可以避免 delete 与 dispatch/review/integrate 的竞态。

---

## 4. 后台清理点

优先复用现有生命周期收尾，不要增加新的长期 daemon。

可以在这些位置触发 best-effort cleanup：

```
run_worker() finally
auto_dispatch reconcile 前后
pipeline cycle 开头/结尾
API list tasks 时禁止做重清理
```

推荐抽一个极小函数，例如：

```
request_task_delete(...)
finalize_task_delete_if_safe(...)
```

不要为删除功能新增完整 service/runtime 层。

---

## 5. UI 与“只读”原则的新定义

UI 不再是绝对只读。

正确边界变成：

```
UI 不做执行控制：
- 不 cancel
- 不 retry
- 不 reassign
- 不 review pass/fix
- 不 integrate

UI 可以做记录管理：
- 删除任务记录
```

Delete 不得改变正在运行的 Agent Job。

---

## 6. PR #35 如何处理

当前 PR #35 的：

```
localStorage hiddenTasks
清除已结束
恢复隐藏
```

不是最终需求。

可以保留为“本地隐藏”辅助功能，也可以在真正 Delete 上线时删掉，避免两个相似动作造成混淆。

如果保留，文案必须严格区分：

```
隐藏
vs
删除
```

不允许继续把“清除已结束”当作删除任务功能的完成证据。

---

## 7. 验收场景

### A. 删除 DONE

```
DONE task
→ 点击删除
→ API 200
→ tasks/<id> 消失
→ 刷新 UI 后不存在
```

### B. 删除 RUNNING

```
RUNNING task
→ 点击删除
→ API 202 pending
→ UI 立即不再显示
→ Agent Job 仍继续运行
→ CodeArts 进程不被 kill
→ 任务自然结束
→ Bridge 完成 fetch / cleanup
→ tasks/<id> 最终被删除
```

必须确认：

```
没有调用 Agent cancel
没有 CANCELLED 状态
没有 SIGTERM/SIGKILL 因 delete 产生
```

### C. 删除与 scheduler 竞态

```
READY task
→ delete marker
→ auto_dispatch 同时运行
→ task 不得再被派发
```

### D. 删除与 integration 竞态

```
APPROVED task
→ delete
→ 不得随后被 integrate_loop 拾取
```

---

## 8. Do Not

不要：

```
把任务目录在 RUNNING 时直接 rm -rf
把 delete 映射成 cancel
为了 delete 新增第二套 task 状态机
只做 localStorage 隐藏却宣称已经删除
```

目标就是一句话：

```
任务记录可以删；执行中的任务，删记录不等于停执行。
```
