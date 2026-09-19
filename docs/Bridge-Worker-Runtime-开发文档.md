# Bridge Worker Runtime 开发文档

> 文件建议：`docs/Bridge-Worker-Runtime-开发文档.md`  
> 版本：0.1  
> 日期：2026-09-19  
> 仓库：`nathanxiangang-web/CodeartsBridge`  
> 目标：先根治当前 4 个 Worker 大面积超时，再把远程执行从“长连接 SSH + Shell 字符串”升级为“Worker 本地执行代理 + 可恢复控制协议”。

---

# 0. 结论

当前问题不应该继续靠“增加超时时间”“继续改 WORKER.md 提示词”“换一种 heredoc/base64 写法”解决。

从当前仓库实现和 4 个 Worker 的实时日志看，存在一个更直接的 P0 根因：

- `SshTransport` 已经通过 SSH 登录到 Worker 主机，并在远端执行 `codearts`。
- 远端命令也已经先执行 `cd -- <projectRoot>`，因此此时 `codearts` 看到的项目目录其实是 **Worker 本机目录**。
- 但 `SshTransport` 又调用 `get_remote_access_directive(host_name, remote_project_path)`，向远端 AI 注入“目标源码是远程的，所有读写都必须再次通过 ssh”的指令。
- 结果变成：

```text
Bridge 控制端
  -> SSH 到 192.168.178.52
      -> 启动远端 codearts
          -> codearts 又执行 ssh nathan@192.168.178.52
              -> 再访问自己本机的 /home/nathan/bridge-python
```

这就是当前截图里反复出现：

```text
bash ssh -o BatchMode=yes nathan@192.168.178.52 ...
bash ssh -o BatchMode=yes nathan@192.168.178.50 ...
bash ssh -o BatchMode=yes nathan@192.168.178.53 ...
bash ssh -o BatchMode=yes nathan@192.168.178.51 ...
```

的原因。

随后出现第二层问题：

```text
内置 Write 被任务指令限制
-> Worker 退化为 bash + ssh 写文件
-> heredoc / 多行 Python / 引号 / triple quote 被 Bash Tool 的命令解析器误判
-> Worker 不断换写法重试
-> 没有有效产出
-> 一直跑到 hard timeout
```

仓库 2026-09-19 最新的两个修复：

- `6a0f3fd`：禁止 heredoc，强制 `python3 -c + base64`
- `36cdc66`：强制 `python3 -c` 外层使用单引号

解决的是**症状**，不是根因。

本方案分两步：

1. **P0：立刻修掉 nested self-SSH。**
2. **P1：开发独立的 Bridge Worker Runtime（BWR / bridge-worker-agent），彻底把任务生命周期从长连接 SSH 中剥离出来。**

P0 不应等待 P1。P0 修复后，当前四台 Worker 应先恢复可用。

---

# 1. 当前实现确认

当前 Bridge 的 `bridge-dev` 系列项目配置：

```text
192.168.178.52 -> /home/nathan/bridge-python
192.168.178.50 -> /home/nathan/bridge-python
192.168.178.53 -> /home/nathan/bridge-python
192.168.178.51 -> /home/nathan/bridge-python
```

均使用：

```json
{
  "transport": "ssh"
}
```

`src/bridge/transport/ssh.py` 当前执行逻辑本身已经是：

```text
控制端
  -> ssh worker
  -> cd projectRoot
  -> codearts run ...
```

因此在 `SshTransport` 模式下，AI 对项目文件的正常视角应该是：

```text
LOCAL
```

而不是：

```text
REMOTE OVER SSH
```

真正需要 `get_remote_access_directive()` 的场景是：

```text
ssh-shell
```

即：

```text
codearts 在控制端本机运行
项目在另一台远端机器
```

这两个 transport 的语义必须严格分开。

---

# 2. P0：立即修复当前四 Worker 全超时

## 2.1 修改目标

文件：

```text
src/bridge/transport/ssh.py
```

当前错误逻辑：

```python
remote_directive = get_remote_access_directive(host_name, remote_project_path)

prompt = build_worker_core_prompt(
    ...
    project_path=remote_project_path,
    remote_directive=remote_directive,
)
```

修改为：

```python
prompt = build_worker_core_prompt(
    worker_contract=f"{remote_protocol}/WORKER.md",
    meta_path=f"{remote_task}/META.json",
    instructions=remote_instruction_paths,
    outbox_path=remote_outbox,
    project_path=remote_project_path,
    remote_directive=(
        "The CodeArts process is already running on the target worker host. "
        f"Treat project '{remote_project_path}' as a LOCAL project directory. "
        "Use normal local read/edit/write/test tools inside that project. "
        "Do not SSH to this worker host to access its own project."
    ),
)
```

更推荐把这段定义成独立函数：

```text
get_worker_local_access_directive()
```

放到：

```text
src/bridge/codearts.py
```

从而明确两套语义：

```text
SshTransport
    -> LOCAL worker directive

SshShellTransport
    -> REMOTE access directive
```

## 2.2 不允许做的“假修复”

P0 阶段禁止：

- 把 15 分钟改回 30/60/120 分钟。
- 再增加更多 heredoc 规则。
- 再要求 AI 自己发明 Python 拼接脚本。
- 再增加“失败后继续多试几次”的提示词。
- 把错误归因为模型不会写文件。
- 同时修改多个 transport，造成回归面扩大。

目标只有一个：

> `transport=ssh` 时，远端 CodeArts 不再 SSH 到自己。

---

# 3. P0 测试设计

新增：

```text
tests/test_ssh_transport_semantics.py
```

至少包含以下测试。

## 3.1 Prompt 语义测试

断言 `SshTransport` 构造的 prompt：

必须包含：

```text
already running on the target worker host
Treat project ... as a LOCAL project directory
Do not SSH to this worker host
```

不得包含：

```text
The target source is remote
Access project ... only through non-interactive commands using ssh
Run every project inspection, edit, test, and build command over SSH
```

## 3.2 ssh-shell 回归测试

`SshShellTransport` 必须继续包含：

```text
The target source is remote
```

防止修复 ssh transport 时误伤 ssh-shell。

## 3.3 远程命令结构测试

捕获 `subprocess.Popen()` 参数，断言控制端只发生一层 SSH：

```text
ssh -o BatchMode=yes <worker> "cd -- <project> && codearts ..."
```

不得在注入给 AI 的 prompt 中要求第二层 SSH。

## 3.4 真实单 Worker Smoke

先只启用 `.50`。

创建 3 分钟 smoke task：

```markdown
目标：
在项目允许路径创建 tests/_bridge_write_smoke.txt，
内容为 `bridge-local-write-ok`，
读取验证内容，
删除该临时文件，
写出 RESULT.md / TESTS.md / DIFF.stat。
禁止主动执行 ssh。
```

验收：

```text
总耗时 < 120s
状态进入 REVIEW_REQUIRED 或 DONE
session.log 中没有 ssh nathan@192.168.178.50
没有 failed to parse target path
没有 heredoc workaround
没有“Write tool rejected because task requires SSH”
```

`.50` 通过后按：

```text
.52 -> .53 -> .51
```

逐台 smoke。

四台全部通过后才能恢复并发开发。

---

# 4. 为什么仍然要开发独立 Worker Runtime

即使 P0 修好，当前 SSH Transport 仍有结构性问题。

当前任务生命周期：

```text
Bridge
  -> Popen(ssh ...)
      -> 长时间保持 SSH 会话
          -> 远端 CodeArts
              -> 完成 / 超时
```

这意味着：

- 控制面任务生命周期和 SSH TCP 会话绑定。
- 中途网络抖动会影响控制面判断。
- Bridge 重启后很难重新接管原进程。
- soft timeout 目前主要只是“拉一次 outbox”，不能真正控制远端执行。
- stdout/stderr 主要依赖当前运行进程和最终收集。
- 远端进程、PID、日志、workspace 状态不属于一个独立可恢复 runtime。
- SSH 同时承担 bootstrap、控制协议、执行协议、文件传输，职责太重。

所以需要把 SSH 降级成：

```text
安装 / 首次部署 / 故障恢复通道
```

正常任务执行改为：

```text
Bridge <-> Worker Runtime API
```

---

# 5. 新组件定义

组件正式名称：

```text
Bridge Worker Runtime
```

进程名：

```text
bridge-worker-agent
```

简称：

```text
BWR
```

定位：

> 部署在每台 Worker 主机上的轻量任务执行守护进程。负责本机 CodeArts 进程、日志、超时、取消、恢复、产物和 heartbeat。Bridge 控制面不再通过长连接 SSH 直接托管任务进程。

首版仍放在 CodeartsBridge 单仓库中开发，不立即拆新仓库。

原因：

- 能复用现有 config / codearts / telemetry / state 数据结构。
- 能由现有 pytest 一起覆盖。
- 降低版本兼容成本。
- 稳定后再决定是否拆成独立 Python package。

---

# 6. 目标架构

```text
                         +----------------------+
                         |   Bridge Control     |
                         | Scheduler / Pipeline |
                         +----------+-----------+
                                    |
                             AgentTransport
                          HTTP JSON / polling
                                    |
           +------------------------+-------------------------+
           |                        |                         |
           v                        v                         v
  +----------------+      +----------------+        +----------------+
  | 192.168.178.52 |      | 192.168.178.50 |        | 192.168.178.53 |
  | bridge-workerd |      | bridge-workerd |        | bridge-workerd |
  +-------+--------+      +-------+--------+        +-------+--------+
          |                       |                         |
          v                       v                         v
     CodeArts CLI             CodeArts CLI             CodeArts CLI
          |                       |                         |
          v                       v                         v
   local project/worktree   local project/worktree    local project/worktree
```

`.51` 同样部署。

关键原则：

```text
AI 在 Worker 本机运行
源码在 Worker 本机
文件编辑是本地操作
测试是本地操作
Git 是本地操作
Bridge 只发送结构化任务
```

正常运行路径禁止：

```text
AI -> ssh -> 自己
```

---

# 7. 目录结构

新增：

```text
src/bridge/agent/
├── __init__.py
├── server.py
├── auth.py
├── models.py
├── store.py
├── runner.py
├── watchdog.py
├── recovery.py
├── artifacts.py
├── fs_guard.py
└── cli.py

src/bridge/transport/
└── agent.py

deploy/
├── bridge-worker-agent.service
└── install-worker-agent.sh

tests/
└── agent/
    ├── test_agent_api.py
    ├── test_agent_runner.py
    ├── test_agent_timeout.py
    ├── test_agent_cancel.py
    ├── test_agent_recovery.py
    ├── test_agent_security.py
    └── test_agent_transport.py
```

继续使用 Python 标准库 HTTP Server，和当前：

```text
src/bridge/api/server.py
```

保持技术路线一致，不在 MVP 新增 FastAPI / Node 生产依赖。

---

# 8. Agent 本地数据目录

每台 Worker：

```text
~/.codex-glm-bridge/agent/
├── agent.json
├── jobs/
│   └── <job-id>/
│       ├── request.json
│       ├── state.json
│       ├── stdout.jsonl
│       ├── stderr.log
│       ├── process.json
│       ├── events.jsonl
│       └── artifacts/
├── locks/
└── runtime/
```

要求：

- 所有 state 更新原子写。
- job 状态必须能在 daemon 重启后恢复。
- 日志不得只存在内存。
- PID 和 process group 必须持久化。
- 不保存 CodeArts 密钥内容。
- API 返回日志前经过 `sensitive_mask()`。

---

# 9. Agent API

## 9.1 Health

```http
GET /v1/health
```

响应：

```json
{
  "ok": true,
  "agentVersion": "0.1.0",
  "hostname": "be-02-task-api-w02-20260919",
  "activeJobs": 1,
  "capacity": 1,
  "codearts": {
    "available": true,
    "path": "/home/nathan/.codeartsdoer/installers/bin/codearts"
  }
}
```

## 9.2 创建任务

```http
POST /v1/jobs
Authorization: Bearer <token>
Content-Type: application/json
```

请求：

```json
{
  "taskId": "UI-02-001",
  "attempt": 1,
  "projectRoot": "/home/nathan/bridge-python",
  "cliPath": "/home/nathan/.codeartsdoer/installers/bin/codearts",
  "model": "huaweicloud-maas/GLM-5.2",
  "mode": "auto",
  "prompt": "...",
  "softTimeoutSeconds": 480,
  "hardTimeoutSeconds": 900,
  "sessionId": null
}
```

响应：

```json
{
  "jobId": "01J...",
  "state": "STARTING"
}
```

## 9.3 查询任务

```http
GET /v1/jobs/<jobId>
```

响应：

```json
{
  "jobId": "01J...",
  "taskId": "UI-02-001",
  "state": "RUNNING",
  "pid": 12345,
  "startedAt": "...",
  "lastEventAt": "...",
  "elapsedSeconds": 74,
  "softLimitReached": false,
  "exitCode": null
}
```

## 9.4 增量日志

```http
GET /v1/jobs/<jobId>/events?cursor=100
```

响应：

```json
{
  "cursor": 124,
  "events": [...]
}
```

MVP 先做 cursor polling。

不要第一版就做跨主机 SSE。

Bridge 自己对浏览器仍然可以继续提供 SSE。

这样即使一次 HTTP 请求断开，任务仍在 Agent 本地正常运行。

## 9.5 取消

```http
POST /v1/jobs/<jobId>/cancel
```

Agent：

```text
SIGTERM process group
等待 5 秒
仍存活 -> SIGKILL process group
保存最终状态
```

## 9.6 获取产物

```http
GET /v1/jobs/<jobId>/artifacts
```

返回：

- outbox 文件清单
- runtime logs
- checkpoint
- diff/stat
- session metadata

首版不要开放任意路径下载。

只能返回 job 目录和允许 outbox 范围内的文件。

---

# 10. Agent Runner

`runner.py` 只做本地进程。

禁止：

```text
shell=True
bash -c "<巨大字符串>"
ssh "<远端命令>"
```

必须：

```python
subprocess.Popen(
    [cli] + args,
    cwd=project_root,
    stdout=stdout_file,
    stderr=stderr_file,
    text=True,
    start_new_session=True,
)
```

这样：

- prompt 是 argv 元素，不经过 Bash 二次解析。
- `()`、`$`、引号、换行不会再被远程 Shell 当语法重解释。
- 项目路径由 `cwd` 控制，不需要 `cd && ...` 拼接。
- PID/process group 可稳定管理。

---

# 11. Timeout 机制

当前 soft timeout 只“抓一次 outbox”是不够的。

BWR 采用本地 Watchdog。

## 11.1 soft timeout

到达 soft deadline：

```text
RUNNING
  -> SOFT_LIMIT
```

立即执行：

1. 写 `softLimitReached=true`。
2. 保存当前 git status。
3. 保存当前 git diff。
4. 复制现有 outbox。
5. 发事件给 Bridge。
6. 不再增加额外 task retry。
7. 允许进程继续到 hard deadline。

MVP 不强行杀进程。

原因：首版先解决“任务失联”和“工作丢失”。

## 11.2 hard timeout

到达 hard deadline：

```text
SIGTERM process group
-> grace 5s
-> SIGKILL
```

随后：

```text
如果已有正式 deliverables
    -> COMPLETED_WITH_TIMEOUT
否则如果有 git diff / checkpoint
    -> ASSISTANCE_REQUIRED
否则
    -> TIMED_OUT
```

Bridge 再映射到现有 canonical state。

## 11.3 自动 salvage

即使 Worker 没写 outbox，也必须自动生成：

```text
runtime-salvage/
├── git-status.txt
├── DIFF.patch
├── DIFF.stat
├── last-events.jsonl
└── PROCESS.json
```

目标：

> 超时可以失败，但不能再“白跑 15 分钟什么都没有”。

---

# 12. 文件写入兜底工具

即使 P0 修复后，CodeArts 自带 Write 偶尔仍可能出现权限或 Tool Parser 问题。

因此 BWR 同时提供一个极简本地 CLI：

```text
bridge-fs
```

只允许操作当前项目根目录。

示例：

```text
bridge-fs write-b64 tests/test_task_api.py BASE64_DATA
bridge-fs read tests/test_task_api.py
bridge-fs exists tests/test_task_api.py
```

禁止：

```text
bridge-fs write ../../../etc/passwd
```

实现规则：

```python
resolved = (project_root / relative_path).resolve()
resolved.relative_to(project_root.resolve())
```

必须防：

- `..` 路径逃逸
- symlink escape
- absolute path escape
- 写 `.ssh`
- 写 token/config secret 目录

为什么保留 base64：

> base64 可以把任意源码内容变成单一安全 argv，AI 不需要再构造 heredoc、多层 shell quote、三引号或嵌套 SSH 命令。

但注意：

> `bridge-fs` 是 fallback，不应代替正常内置 editor。

---

# 13. Bridge 侧新增 AgentTransport

新增：

```text
src/bridge/transport/agent.py
```

实现现有：

```python
TransportBase
```

因此 `worker.py` 不需要重写任务状态机。

执行过程：

```text
AgentTransport.run()
  -> POST /v1/jobs
  -> 每 2 秒 GET /v1/jobs/{id}
  -> 增量拉 events
  -> 完成后拉 artifacts
  -> 映射 TransportResult
```

关键收益：

控制端进程可以重启。

只要 agent 任务还在：

```text
Bridge restart
-> reconcile
-> GET agent job
-> 重新接管
```

不再因为本地 `Popen(ssh)` 句柄消失就失去任务。

---

# 14. Worker 配置扩展

`workers.json` 增加：

```json
{
  "id": "bus-w02-dev",
  "transport": "agent",
  "endpoint": "http://192.168.178.50:8765",
  "agentTokenEnv": "BRIDGE_AGENT_W02_TOKEN",
  "cliPath": "/home/nathan/.codeartsdoer/installers/bin/codearts",
  "concurrencyLimit": 1,
  "enabled": true,
  "capabilities": ["implement", "review", "test"]
}
```

不要把 token 明文写进：

```text
workers.json
Git
日志
UI
```

第一版部署时使用环境变量。

---

# 15. 安全边界

MVP 至少必须做到：

1. Agent 只允许白名单项目根目录。
2. `projectRoot` 必须 resolve 后匹配 agent config allowlist。
3. API 必须 Bearer Token。
4. Token 使用 `hmac.compare_digest()` 比较。
5. 监听 LAN 时用防火墙只允许 Bridge 控制节点 IP。
6. 日志调用现有 `sensitive_mask()`。
7. API 不提供任意 shell endpoint。
8. API 不提供任意文件读取 endpoint。
9. Cancel 只能作用于该 Agent 自己创建的 process group。
10. Agent 不接受客户端传任意环境变量；使用 allowlist。

MVP 不需要立刻上 mTLS。

后续跨不可信网络再加：

```text
HTTPS / mTLS
```

---

# 16. systemd 服务

新增：

```text
deploy/bridge-worker-agent.service
```

建议：

```ini
[Unit]
Description=CodeartsBridge Worker Agent
After=network.target

[Service]
Type=simple
User=nathan
WorkingDirectory=/home/nathan/bridge-python
Environment=PYTHONUNBUFFERED=1
EnvironmentFile=-/home/nathan/.config/codeartsbridge/agent.env
ExecStart=/home/nathan/bridge-python/.venv/bin/bridge-worker-agent \
  --listen 0.0.0.0 \
  --port 8765 \
  --root /home/nathan/.codex-glm-bridge/agent \
  --config /home/nathan/.config/codeartsbridge/agent.json
Restart=always
RestartSec=2
KillMode=mixed

[Install]
WantedBy=multi-user.target
```

`.53` 如果继续使用不同用户，需要独立配置。

不要默认全部假设 `/home/nathan`。

---

# 17. Doctor 扩展

`bridge doctor` 增加：

```text
Agent reachability
Agent version
CodeArts CLI available
Project root allowed
Write smoke
Git available
Disk free
Current active jobs
Zombie process
Clock skew
```

输出示例：

```text
W01  192.168.178.52  agent=OK  codearts=OK  project=OK  active=0
W02  192.168.178.50  agent=OK  codearts=OK  project=OK  active=1
W03  192.168.178.53  agent=OK  codearts=OK  project=OK  active=0
W04  192.168.178.51  agent=OK  codearts=OK  project=OK  active=0
```

UI 后续直接使用这些真实 health 数据。

---

# 18. 开发顺序

## Wave P0：止血

Owner：1 人直接修，允许暂时绕过 Bridge Dogfooding。

任务：

```text
P0-01 修 SshTransport nested self-SSH
P0-02 加 transport semantics 单测
P0-03 .50 smoke
P0-04 四机 smoke
```

验收后再恢复 Bridge 派发。

预计代码量：

```text
< 150 行生产代码
< 250 行测试
```

## Wave A：Agent MVP

### W01：Agent HTTP / Auth / Model

负责：

```text
src/bridge/agent/server.py
src/bridge/agent/auth.py
src/bridge/agent/models.py
```

验收：

```text
health
POST job
GET job
cancel API
Bearer auth
```

### W02：Runner / Store / Watchdog

负责：

```text
runner.py
store.py
watchdog.py
recovery.py
```

验收：

```text
本地启动 CodeArts
PID 持久化
timeout
cancel
daemon restart recovery
```

### W03：AgentTransport / Bridge Integration

负责：

```text
src/bridge/transport/agent.py
config.py
worker.py 最小适配
doctor.py
```

验收：

```text
TransportBase contract
任务可正常进入 REVIEW_REQUIRED
Bridge restart 后可重新查询 agent task
```

### W04：Testing / Deployment / Rollout

负责：

```text
tests/agent/*
deploy/bridge-worker-agent.service
deploy/install-worker-agent.sh
docs
```

验收：

```text
四机安装
smoke matrix
failure injection
rollback
```

---

# 19. 开发 DAG

```text
P0-01 nested SSH fix
        |
        v
P0-02 tests
        |
        v
P0-03 one-worker smoke
        |
        v
P0-04 four-worker smoke
        |
        +-----------------------+
        |                       |
        v                       v
A-01 Agent API             A-02 Runner/Store
        |                       |
        +-----------+-----------+
                    v
             A-03 AgentTransport
                    |
                    v
             A-04 Doctor/Deploy
                    |
                    v
             A-05 One Worker Canary
                    |
                    v
             A-06 Four Worker Rollout
                    |
                    v
             A-07 SSH Transport Legacy
```

最终：

```text
agent = 默认
ssh = fallback / bootstrap
ssh-shell = 特殊远程操作
remote-worktree = 保留兼容，后续评估是否由 agent workspace 替代
```

---

# 20. 测试矩阵

## 单元测试

必须覆盖：

```text
auth success/fail
invalid project root
path traversal
agent duplicate task id
concurrency limit
normal process completion
non-zero exit
soft timeout
hard timeout
cancel
daemon restart
dead pid recovery
log cursor
artifact fetch
sensitive mask
```

## 集成测试

使用 fake CodeArts runner：

```text
sleep
stdout JSONL
stderr
create outbox
exit 0
exit 1
ignore SIGTERM
```

覆盖：

```text
Bridge -> AgentTransport -> fake worker -> artifacts
```

## 真实 Smoke

每台 Worker：

```text
1. read
2. write
3. edit
4. pytest targeted
5. git diff
6. outbox
```

每项硬限制：

```text
< 5 min
```

任何 smoke 超时：

```text
禁止直接全量 rollout
```

---

# 21. 故障注入验收

必须主动测试，不要只跑 happy path。

## 场景 A：Bridge 控制端重启

执行中重启 Bridge。

预期：

```text
Agent task 继续运行
Bridge 启动后重新发现 job
不重复启动第二个 CodeArts
```

## 场景 B：HTTP 暂时不可达 30 秒

预期：

```text
Worker 本地继续
恢复连接后状态补齐
```

## 场景 C：CodeArts 卡死

预期：

```text
hard timeout 后 process group 被杀
保留 salvage
状态不永久 RUNNING
```

## 场景 D：Agent 重启

预期：

```text
重新读取 jobs state
检查 PID
存活则重新跟踪
死亡则收敛为 terminal/recovery state
```

## 场景 E：非法 projectRoot

例如：

```text
/etc
/root/.ssh
../../
```

预期：

```text
HTTP 403
不启动任务
```

---

# 22. 成功指标

当前阶段不要追求复杂指标，先追 6 个硬指标：

```text
1. self-SSH 次数 = 0
2. parser path error = 0
3. heredoc workaround = 0
4. 15 分钟零产出 timeout = 0
5. 控制端重启后任务可恢复观察 = 100%
6. 四 Worker 连续 20 个小任务完成率 >= 95%
```

额外记录：

```text
task duration p50 / p95
timeout rate
retry rate
write failure rate
agent reconnect count
salvage success rate
```

---

# 23. Rollout 策略

不要一次把四台全部切到 agent。

顺序：

```text
Stage 0
修 SshTransport

Stage 1
W02 (.50) agent canary

Stage 2
W01 (.52) + W02 (.50)

Stage 3
W03 (.53)

Stage 4
W04 (.51)

Stage 5
agent 成为默认 transport
```

每阶段至少：

```text
5 个真实任务
```

无 timeout / stuck / artifact loss 后进入下一阶段。

---

# 24. 回滚

保留：

```text
transport=ssh
```

作为 fallback。

如果 Agent rollout 失败：

```json
{
  "transport": "ssh"
}
```

即可回滚。

因此第一版不要删除：

```text
ssh.py
ssh_shell.py
remote_worktree.py
```

等 Agent 连续稳定一段时间后再决定收敛 transport。

---

# 25. 当前 UI 开发计划如何处理

当前 `docs/开发文档.md` 的 Control Center UI 计划本身可以保留。

但执行优先级调整为：

```text
P0 nested SSH fix
    ↓
Agent Runtime MVP
    ↓
Worker 稳定性验收
    ↓
恢复 UI-00 / UI-01 / UI-02 / UI-03 / UI-04
```

原因：

> 现在继续让 4 个 Worker 并行开发 UI，只会继续烧时间、烧模型额度、制造半成品和 timeout 垃圾状态。

基础执行层不稳定时，不应该继续扩大上层并发。

---

# 26. Bootstrap 例外

现有开发规则强调 Dogfooding。

本次允许一个明确例外：

```text
修复导致 Dogfooding 本身失效的 P0 基础设施问题时，
允许直接在单一可信工作区开发、测试、提交。
```

因此：

- P0 nested SSH fix：直接开发。
- Agent 最小可启动骨架：允许直接开发。
- 当单 Worker canary 通过后：后续功能重新使用 Bridge 自己派发。

这不是绕过流程，而是修复流程本身。

---

# 27. 第一轮可直接创建的任务

## TASK-P0-SSH-SEMANTICS

```text
Owner: W01 / Architect direct
Target: 45 min
Hard: 60 min

Files:
- src/bridge/transport/ssh.py
- src/bridge/codearts.py
- tests/test_ssh_transport_semantics.py

Acceptance:
- SshTransport prompt treats projectRoot as local
- no self-SSH directive
- SshShellTransport unchanged
- targeted tests pass
```

## TASK-AGENT-API

```text
Owner: W01
Target: 2h

Files:
- src/bridge/agent/server.py
- auth.py
- models.py

Acceptance:
- health
- create/get/cancel job
- auth
```

## TASK-AGENT-RUNNER

```text
Owner: W02
Target: 2h

Files:
- runner.py
- store.py
- watchdog.py
- recovery.py

Acceptance:
- local argv execution
- timeout/cancel
- persisted job state
```

## TASK-AGENT-TRANSPORT

```text
Owner: W03
Target: 2h

Files:
- src/bridge/transport/agent.py
- config.py
- worker.py

Acceptance:
- implements TransportBase
- one fake end-to-end task
```

## TASK-AGENT-QA

```text
Owner: W04
Target: 2h

Files:
- tests/agent/*
- deploy/*

Acceptance:
- fault injection
- service install
- canary procedure
```

---

# 28. Definition of Done

本项目不是“Agent API 能启动”就完成。

必须同时满足：

```text
[ ] SshTransport 不再 nested self-SSH
[ ] 四台旧 ssh worker smoke 全通过
[ ] Agent 可独立启动
[ ] Agent API 有认证
[ ] Agent 只允许白名单项目
[ ] Agent 用 argv 启动 CodeArts，不用 shell=True
[ ] Agent 能持久化 PID/state/log
[ ] Agent 能 hard timeout
[ ] Agent 能 cancel
[ ] Agent 能 salvage diff/outbox
[ ] Bridge AgentTransport 可运行真实任务
[ ] Bridge 重启后能重新观察执行中任务
[ ] .50 canary 5 个任务通过
[ ] 四 Worker 累计 20 个任务完成率 >= 95%
[ ] 无任务因 heredoc/bash parser 白跑到 hard timeout
```

---

# 29. 当前最优执行动作

现在不要先写 Agent。

执行顺序必须是：

```text
1. 停掉当前已经明显陷入 parser retry 的四个任务
2. 修 src/bridge/transport/ssh.py 的 nested self-SSH
3. 加 test_ssh_transport_semantics.py
4. 只部署到 .50
5. 跑 1 个 3 分钟 write smoke
6. 通过后部署 .52/.53/.51
7. 四机 smoke
8. 恢复小任务
9. 再并行开发 Bridge Worker Runtime
```

如果第 5 步通过，基本就证明当前截图里的“全超时”主因已经被抓住。

---

# 30. 最终目标

最终 Bridge 的执行层应该从：

```text
Prompt
-> SSH
-> remote shell
-> quote
-> CodeArts
-> AI 再 SSH
-> shell parser
-> file write
```

收敛成：

```text
Bridge structured job
-> Worker Agent
-> local CodeArts argv
-> local project
-> normal editor
-> local tests
-> persisted result
```

一句话：

> **SSH 只负责“到机器”，不要再负责“托管整个 AI 任务生命周期”；AI 已经在 Worker 上，就必须把 Worker 上的源码当本地源码。**
