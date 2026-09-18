# ADR-003: AI 职责划分

> 状态: Accepted | 日期: 2026-09-18

## 背景

多 AI 协作时需要明确职责边界，避免冲突和重复工作。

## 决策

```
AI 决定 WHAT（做什么）
Bridge 决定 WHEN/WHERE/PROCESS（何时/何地/如何调度）
Worker 决定 HOW（怎么实现）
```

### 角色职责

| 角色 | 职责 |
|------|------|
| User | 需求、业务优先级、重大架构冲突、最终发布 |
| Architect AI | 理解需求、拆分 Task、建 DAG、指定验收、Review、控制集成 |
| Bridge | 调度、隔离、锁、租约、进程、超时、取消、重试、状态、证据 |
| W01 (Runtime) | daemon、process supervisor、transport runtime、timeout、cancel |
| W02 (State) | state、task lifecycle、attempt、result classifier、model routing |
| W03 (Scheduler) | dispatch、worker registry、resource、affinity、priority、health |
| W04 (QA) | review、test、regression、E2E、CI、acceptance |

### 核心原则

1. 不让所有 AI 重新理解整个项目
2. 不让 Architect 长时间写普通实现代码
3. 不让 Worker 自己决定跨模块架构
4. 不让两个实现 Worker 同时修改共享核心文件
5. 让 W04 独立验证，而不是参与普通编码

## 理由

- AI 擅长理解需求和规划，不擅长确定性控制
- Bridge 用确定性程序解决调度/隔离/超时等问题，比 AI 决策更可靠
- Worker 专注窄范围实现，效率最高
- W04 独立验收避免"写代码的人证明自己正确"

## 影响

- 推进文档作为 Architect AI 的主文档
- 每个 Worker Task 限定一个交付物、一个故障域
- W01/W02/W03 尽量并行但不修改同一核心边界