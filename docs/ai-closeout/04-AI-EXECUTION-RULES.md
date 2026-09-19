# 04 — AI 执行规则

这份规则用于防止后续 AI 再次出现“规划很漂亮、代码也很多、但没有真的用起来”。

## 1. Definition of Real

一个功能只有下面 5 项全部成立才算完成：

```
1. 有真实入口
2. 默认运行路径会调用
3. 会产生真实副作用/状态变化
4. 用户能观察到结果
5. 有真实 E2E 验证
```

例如：

```
Supervisor.tick() 被调用
```

不等于监督功能完成。

必须证明：

```
真实 task started
-> deadline 注册
-> 时间到
-> inspector 读取真实 task
-> 产生真实动作/告警
-> UI/状态可看到
```

否则就是“流程占位”。

## 2. 每次改代码前

必须先写出：

```
ENTRYPOINT:
CALL PATH:
STATE BEFORE:
REAL SIDE EFFECT:
STATE AFTER:
OBSERVABLE RESULT:
FAILURE PATH:
```

写不出来，不准开始新增实现。

## 3. 删除优先规则

发现以下情况默认删除：

- 只有测试调用，运行时没有调用。
- 默认 flag 永久关闭。
- 和另一套模块解决同一个问题。
- handler 默认返回 None/no-op。
- 只为了“未来可能需要”。
- README 有、代码默认路径没有。
- 代码有、部署脚本从不启动。
- 状态会变，但真实动作没发生。

## 4. 禁止“状态模拟成功”

禁止：

```
set_state(INTEGRATED)
set_state(DONE)
```

去代替：

```
git cherry-pick
tests
artifact fetch
worker completion
```

状态必须描述事实，不得推动事实。

## 5. 测试规则

测试分三层：

### L1 单元测试

验证纯函数/边界。

### L2 组件集成

例如：

```
Bridge -> Fake Agent
Agent -> Fake CodeArts
```

### L3 真实主链

至少保留一组真实验收：

```
Bridge
-> 实际 Worker Agent
-> 实际 CodeArts CLI
-> 实际 project repo
-> 实际 git commit/integration
-> UI 实时回显
```

L1/L2 全绿不能替代 L3。

## 6. PR 规则

一个 PR 只允许一个主题。

PR 描述必须包含：

```
删除了什么
保留了什么
主链路发生什么变化
真实验收怎么跑
失败时会怎么表现
```

不接受：

- “新增架构层以兼容旧架构”
- “先留着以后再清”
- “临时加 flag”
- “为了通过测试重新恢复旧功能”

## 7. 代码量规则

当前阶段优先：

```
deleted lines > added lines
```

若新增代码明显多于删除代码，必须重新说明为什么不是在继续复杂化。

## 8. AI 遇到不确定模块时

不要猜。

执行：

```
1. 搜引用
2. 搜入口
3. 搜 systemd/deploy
4. 搜 CLI/API
5. 跑真实场景
6. 再决定 KEEP / WIRE / DELETE
```

默认不是“保守保留”，默认是“没有真实价值就删除”。
