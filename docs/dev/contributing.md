# 贡献说明

本文替代原根目录 `CONTRIBUTE.md`，用于说明当前版本的贡献流程与注意事项。

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

- `gemini 3.1 pro`
- `kimi 2.6`

如果希望统一一套模型做全栈贡献，也推荐直接使用：

- `gpt-5.5`
- `claude opus 4.7`

模型建议不是硬性门禁，但复杂后端改动尽量不要交给逻辑稳定性明显较弱的模型首发。

## 改动前先理解当前边界

最重要的几条：

- `main.py` 与 `bootstrap.py` 的职责不能混
- 配置模型位于 `src/infrastructure/config/models/`：持久化配置在 `plugin_config_models.py`，运行态设置在 `runtime_settings.py`，sender 策略兼容在 `sender_strategy_models.py`；`src/infrastructure/config/datamodels.py` 仅保留兼容导出。共享常量只认 `src/shared/constants.py`
- 订阅/用户配置只认 `-100` 继承
- `handlers` 是当前内容处理入口，不要把旧翻译管道加回来
- Plugin Pages 不负责新建订阅和 TOML 导入导出

如果准备做的事和这些边界冲突，需要先明确说明为什么。

## 推荐的贡献流程

1. 明确问题或目标
2. 先阅读相关代码与现有测试
3. 小步提交，单次改动尽量围绕一个目的
4. 先补或更新测试，再补文档
5. 通过 lint 与最小回归检查后再提交 PR

## 文档同步要求

以下情况不要只改代码：

- 命令行为变化
- 配置项变化
- 管理页入口变化
- handler / AI / KB 能力变化

至少同步更新：

- `README.md`
- `docs/`

必要时再更新：

- `AGENTS.md`
- `CLAUDE.md`
- `CHANGELOG.md`

以下情况通常应直接视为“必须同步文档”：

- 命令行为或参数变化
- Web API / Plugin Pages 行为变化
- 配置项、默认值、继承语义、兼容规则变化
- handler、AI、sender、知识库、去重、重试、推送历史语义变化
- 仓储查询语义、测试推送路径、数据管理能力变化

如果这些变化同时影响维护约定或架构边界，还需要同步更新：

- `AGENTS.md`
- `CLAUDE.md`

## 代码风格

- 优先沿用现有模式，不引入新风格
- 默认使用 ASCII
- 少写无意义注释
- 不要为了局部问题顺手大改 unrelated 模块

## PR 描述建议

建议至少写清楚：

- 背景问题
- 改动范围
- 风险点
- 验证方式

如果是回归修复，最好明确指出“避免了什么回退”。
