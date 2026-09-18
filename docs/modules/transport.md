# transport 模块

> 职责：Worker 执行的传输层，支持 local/ssh/ssh-shell/remote-worktree

## 关键文件

- `src/bridge/transport/base.py` — 传输基类（TransportBase, TransportResult）
- `src/bridge/transport/local.py` — 本地传输
- `src/bridge/transport/ssh.py` — SSH 传输
- `src/bridge/transport/ssh_shell.py` — SSH-shell 传输
- `src/bridge/bridge/transport/remote_worktree.py` — 远程 worktree 传输

## TransportBase.run 签名

```python
def run(
    self, project, worker, task_dir, task_id,
    mode="auto", timeout_seconds=900, soft_timeout_seconds=0,
    session_id=None, attempt=0, baseline=None, quiet=False,
    model=None,  # P1-03: 模型路由
) -> TransportResult
```

## 隔离方式（P0-03）

由 transport 决定，不由 workspaceMode 决定：

| transport + role | 隔离方式 |
|-----------------|---------|
| local + implement | local isolated worktree |
| remote-worktree + implement | remote isolated workspace |
| ssh + implement | existing exclusive |
| review/test | shared readonly |

## 模型传递

所有 transport 接收 `model` 参数，传递给 `new_worker_run_arguments(model=model or REQUIRED_MODEL)`。