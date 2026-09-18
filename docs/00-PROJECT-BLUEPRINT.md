# CodeartsBridge 项目蓝图

> 版本: 2.0.0 | 更新: 2026-09-18

## 定位

CodeartsBridge 是一个面向多 AI 软件开发的轻量级任务控制平面。

**不是** AI 开发平台，**不是** workflow engine，**不是** 权限系统。

## 核心链路

```
User → Architect AI → Task DAG → CodeartsBridge → Dispatcher → W01-W04
     → Patch + Tests + Evidence → QA/Architect Review → Integration → Main
```

## 职责边界

| 角色 | 决定什么 |
|------|---------|
| User | 需求、业务优先级、重大架构冲突 |
| Architect AI | WHAT（任务拆分、验收标准、Review） |
| Bridge | WHEN/WHERE/PROCESS（调度、隔离、超时、取消） |
| Worker | HOW（具体实现） |

## 核心原则

1. AI 决定 WHAT，Bridge 决定 WHEN/WHERE/PROCESS，Worker 决定 HOW
2. 用最少的控制面复杂度，让多个 AI 工程师持续、可靠、低冲突、高利用率地输出可验证代码
3. Bridge 本身保持简单——不提前加入大型数据库、复杂权限、复杂 UI、复杂 workflow DSL

## 最终衡量标准

```
Requirement → Task Planning → Parallel Development → Independent QA → Validated Patch
```

整个链路应越来越短、越来越自动、越来越稳定。

## 当前阶段

- P0（可信控制面）：DONE
- P1（高效率开发优化）：进行中
  - P1-01 doctor 探针：DONE
  - P1-02 优先级调度：DONE
  - P1-03 模型路由：DONE
  - P1-04 策略门控：DONE
  - P1-05 上下文包：DONE
  - P1-06 遥测统计：DONE