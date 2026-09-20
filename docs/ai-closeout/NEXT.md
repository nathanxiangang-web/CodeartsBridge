# NEXT — 下一位 AI 直接从这里开工

审计基线：`main@59ca2e709cad3e03fdad50cdb53c8d0fd2556314`

项目已完成核心收口，不再继续大改 Agent / Scheduler / Lifecycle。

先读：

```
docs/ai-closeout/07-PRODUCTIZATION-ROADMAP.md
```

## 当前第一优先级

### P0：清理死亡 CLI / packaging 入口

最新 closeout 已删除：

```
src/bridge/daemon.py
src/bridge/adaptive.py
src/bridge/cost.py
```

但当前仍残留：

```
src/bridge/cli.py
  adaptive-dispatch
  cost

pyproject.toml
  bridge-daemon = "bridge.daemon:main"
```

先只修这些真实死入口，并增加 CLI contract regression。

不要顺手重构 scheduler、Agent、integration。

## 当前第二优先级：UI

PR #35 已合入 main，Tasks 页已有：

```
清除已结束
恢复隐藏
```

如果现场看不到按钮，先检查部署 host 的 HEAD 和实际返回的 `/js/pages/tasks.js`，不要再实现第二套按钮。

后续 UI 重点：

```
1. Tasks：活跃优先 / 完整状态 / 时间信息
2. Task Detail：RESULT / TESTS / DIFF / commit / integratedSha / failure
3. Thinking：明确区分 live 与 retained history
4. Overview：Worker 当前任务 / elapsed / last event
```

UI 保持 read-only。

## 再后面

Wave A 稳定后再处理：

```
1. 是否把唯一 TaskLoop 并入 bridge serve
2. 删除 application/integration_service.py 的平行 integration 路径
3. 更新 README / deploy truth
```

## 已完成，不要重复

```
Issue #38
Agent outbox archive lifecycle
Review -> APPROVED -> real Integration -> DONE
dispatch 统一到 auto_dispatch + scheduler
supervision / policy / runtime / daemon / dispatch / adaptive / cost 主模块删除
PR #35 task display clear
```

CodeArts `--format json` 下 built-in write/edit 的立即拒绝视为 CLI 限制；当前 bash fallback 是已验证路径，不再围绕它重构 Agent。

完整工作安排见：

```
docs/ai-closeout/07-PRODUCTIZATION-ROADMAP.md
```
