# 贡献说明

## 贡献目标

优先做这些事情：

- 修复命令、推送、去重、历史记录回归
- 完善 Plugin Pages 可管理性
- 提高多平台 sender 稳定性
- 补全文档、测试与排障能力

不建议直接上来做大而散的重构，除非先把行为边界讲清楚。

## AI 贡献

本项目允许使用 AI 协作贡献。

适合 AI 参与的工作包括：

- 后端实现与回归修复
- Plugin Pages 前端实现
- 测试补全
- 文档整理与架构说明
- 排障、日志梳理、兼容性分析

### 模型建议

后端与核心运行链路（`src/`、测试、迁移、调度、命令、仓储、sender）更推荐使用逻辑能力较强的模型：

- `gpt-5.5`
- `claude opus 4.7`
- `glm-5.1`

前端 Plugin Pages（`pages/`）更推荐：

- `gemini 3.5 pro`
- `kimi 2.6`

如果希望统一一套模型做全栈贡献，也推荐直接使用：

- `gpt-5.5`
- `claude opus 4.7`

模型建议不是硬性门禁，但复杂后端改动尽量不要交给逻辑稳定性明显较弱的模型首发。

## 改动前先理解当前边界

改动前先确认自己触碰的是哪条边界，不在这里复制业务规则：

- 架构与启动分工见 [`../project/architecture.md`](../project/architecture.md)
- 领域值、配置模型和常量归属见 [`../project/domain-model.md`](../project/domain-model.md)
- 命令、AI tools、用户配置、推送历史见 [`../project/application.md`](../project/application.md)
- 平台发送、媒体、代理和缓存见 [`../project/platforms.md`](../project/platforms.md)

如果准备做的事和这些边界冲突，需要先明确说明为什么。

## 推荐的贡献流程

1. 明确问题或目标
2. 先阅读相关代码与现有测试
3. 小步提交，单次改动尽量围绕一个目的
4. 先补或更新测试，再补文档
5. 通过 lint 与最小回归检查后再提交 PR

## 文档同步要求

文档同步细则统一维护在 [`maintenance.md`](./maintenance.md#文档同步)。贡献文档只强调一点：不要只改代码而让 README、docs、CHANGELOG 或 agent 入口说明失真。

## 代码风格

通用工程原则见 [`engineering-principles.md`](./engineering-principles.md)。贡献时优先沿用现有模式，不要为了局部问题顺手大改 unrelated 模块。

## PR 描述建议

新代码和修复改动的 PR 目标分支应为 `dev`，不要直接提交到主分支。

建议至少写清楚：

- 背景问题
- 改动范围
- 风险点
- 验证方式

如果是回归修复，最好明确指出“避免了什么回退”。
