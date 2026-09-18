# CodeartsBridge 开发规则

> 版本: 2.0.0 | 更新: 2026-09-18

## Worker 规则

1. 每个 Task 有一个主要交付物、一个故障域、可独立测试
2. 默认 hard timeout 15 分钟
3. Required Changes 不超过 5 项
4. 不允许同时修改多个核心边界
5. FIX 只能修当前交付物的窄缺陷

### Worker 执行循环

```
SEARCH → READ → EDIT → TEST → ANALYZE → EDIT → TEST → DELIVER
```

### 正式交付物

```
RESULT.md | DIFF.stat | TESTS.md | DIFF.patch
```

### 时间不足时

```
CHECKPOINT.md | ASSISTANCE_REQUEST.md
```

### 架构问题

```
BLOCKER.md
```

## Architect 规则

1. 不重新设计整个项目
2. 不跳过 P0 直接开发 P1
3. 先读取 main 最新状态
4. PASS 后合入，更新 baseline
5. 按依赖关系创建下一批 Task
6. W01/W02/W03 尽量并行但不修改同一核心边界
7. W04 始终负责独立 QA
8. 每轮结束更新推进文档

## Review 规则

只能给出：`PASS` | `FIX` | `ARCHITECTURAL_BLOCKER`

- FIX 必须是当前交付物的窄整改
- 新增模块或新增验收阶段 → 建立新的 Task
- 不要不断往原任务追加范围

## UI 回显强制项

1. 运行中必须有持续 heartbeat
2. UI 晚打开能恢复当前状态
3. UI 重启不空白
4. 四 Worker 并发不串回显
5. attempt 间事件不串线
6. terminal 状态一个刷新周期内显示
7. Worker 静默时显示 STALE
8. 不泄露敏感信息或私有 reasoning

## 高效率原则

1. 不让所有 AI 重新理解整个项目
2. 不让 Architect 长时间写普通实现代码
3. 不让 Worker 自己决定跨模块架构
4. 不让两个实现 Worker 同时修改共享核心文件
5. 让 W04 独立验证，而不是参与普通编码
6. Focused test 通过后优先保护交付物，再跑全量测试
7. 达到 soft timeout 时交 checkpoint
8. Bridge 本身保持简单