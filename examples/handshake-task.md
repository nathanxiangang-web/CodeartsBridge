# TASK

## Objective

验证 GLM Worker 能读取桥梁协议和目标项目，并把结构化结果写回任务 outbox。

## Current Situation

这是只读握手项目，项目根目录只包含 README.md。

## Required Changes

不修改项目文件。读取 README.md 后生成 RESULT.md、DIFF.stat、TESTS.md。

## Constraints

- 不修改目标项目。
- 不创建依赖。
- 不执行联网操作。

## Acceptance Criteria

- RESULT.md 明确写出已读取的项目标题。
- DIFF.stat 明确说明没有代码改动。
- TESTS.md 明确说明完成只读握手检查。

## Files

- README.md

## Deliverables

按 WORKER.md 写入任务 outbox。
