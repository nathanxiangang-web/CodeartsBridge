# CodeartsBridge AI 收口工作区

> 作用：这是给后续 AI/Coding Agent 的**第一入口文档**。  
> 审计基线：`main@14652b4f6a70e5f89ec78fde19aaa3c0a9e3ef74`。  
> 当前阶段不是继续堆功能，而是把“代码存在”收口成“真实主链路可用”。

## 0. 当前阶段唯一目标

把 CodeartsBridge 收成一条真实、简单、可观察、可恢复的主链路：

```
任务创建
  -> 唯一调度器
  -> Worker Agent
  -> CodeArts CLI
  -> 实时事件回显
  -> 产物回传
  -> 自动审查
  -> 真实集成
  -> DONE
```

UI 只负责观察，不负责控制。

## 1. AI 开工前必须遵守

1. 先读本目录全部文档，再读代码。
2. 不新增“大而全”架构，不新造抽象层解决旧抽象层问题。
3. 一个功能只有满足“入口 -> 实际调用 -> 状态变化 -> 可观察结果 -> E2E”才算真的存在。
4. 只有单元测试能调用到、但默认运行路径调用不到的代码，按“未接线功能”处理。
5. 两套实现解决同一件事时，不做长期兼容；选一套，迁移，删除另一套。
6. 删除优先于适配。新增代码必须明显少于删除/合并带来的复杂度。
7. 不恢复已砍掉的重 UI、Policy Gate、多层安全控制、项目×Worker 配置矩阵。
8. 每个 PR 只解决一个闭环问题，必须给出真实运行证据。
9. 不允许用“测试通过”代替“真实链路跑通”。
10. 文档和部署脚本必须和代码当前真实行为一致，否则下一位 AI 会继续被旧设计误导。

## 2. 收口后的目标形态

```
Bridge（单一长期运行进程）
├── API
├── 只读 UI
├── Task Loop
│   ├── review
│   ├── dispatch
│   └── integrate
├── EventStore
└── AgentTransport

Worker Agent
├── Runner
├── Watchdog
├── JobStore
└── Recovery
```

不要再形成第三套调度器、第二套 Supervisor、第二套 Review 状态机。

## 3. 下一步执行顺序

先做 `01-RUNTIME-TRUTH.md` 中已经确认的断点，再按 `02-CLOSEOUT-ROADMAP.md` 推进。

最先处理的不是新功能，而是：

```
P0-1 统一长期运行控制循环
P0-2 修正 Review -> Integration -> DONE 的真实状态语义
P0-3 删除/停用“看起来在跑、实际上没接线”的监督流程
P0-4 清理旧调度/旧服务/旧文档，防止 AI 再走回头路
```

## 4. 完成标准

项目收口完成时，应当能用一条真实验收任务证明：

```
create
-> 自动分配 w01~w04
-> Agent 执行
-> UI 持续回显
-> RESULT/TESTS/COMMIT 回传
-> REVIEW_REQUIRED
-> 审查 PASS
-> 真实 cherry-pick
-> 集成测试通过
-> DONE + integratedSha
```

中间任何一步都不能靠人工补状态，也不能靠“模拟成功”推进。
