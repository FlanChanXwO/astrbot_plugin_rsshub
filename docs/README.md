# RSSHub 文档索引

`astrbot_plugin_rsshub` 的补充文档按用途拆分为三个目录：

- [`project/`](./project/README.md): 项目定位、架构、现状与路线图
- [`dev/`](./dev/README.md): 开发环境、测试流程、贡献约定
- [`usage/`](./usage/README.md): 面向使用者的命令、配置、管理页说明

## 文档职责边界

文档按“入口索引、开发流程、项目事实、用户说明”拆分，避免同一规则多处维护：

- `docs/README.md` 只做总索引和阅读路径。
- `docs/dev/` 只写开发、测试、贡献、维护纪律，不复制业务语义。
- `docs/project/overview.md` 只写项目定位和取舍，不维护细节清单。
- `docs/project/architecture.md` 写模块关系和主运行链路。
- `docs/project/domain-model.md` 是领域值、枚举、配置模型、常量归属的唯一细节来源。
- `docs/project/application.md` 写命令、AI tools、用户配置、推送历史等应用层语义。
- 其他 `docs/project/*.md` 按模块深挖流程和实现边界。
- `docs/usage/` 面向用户说明，维护命令、配置、管理页、AI tools 和兼容性说明。

如果多个文档都提到同一概念，应由最具体的专题文档维护细节，其他文档只链接过去。

## 章节索引

### plan

- [`PLAN.md`](./PLAN.md): 当前剩余计划草案，重点是 Stage 3 处理器内部通信与扩展运行时边界

### project

- [`project/overview.md`](./project/overview.md): 项目定位、边界、设计目标与核心取舍
- [`project/architecture.md`](./project/architecture.md): 架构全景、模块关系、运行主链路与配置职责
- [`project/domain-model.md`](./project/domain-model.md): 领域值、枚举语义、配置模型与常量归属
- [`project/application.md`](./project/application.md): 应用层入口、命令边界、AI tools、用户配置与推送历史语义
- [`project/polling.md`](./project/polling.md): Feed 轮询、条件抓取、去重窗口和 dispatch 输入构造
- [`project/dispatch.md`](./project/dispatch.md): 分发、push history 生命周期、失败分类与重试语义
- [`project/platforms.md`](./project/platforms.md): 平台发送差异、媒体预下载、代理、缓存与常量放置规则
- [`project/handlers.md`](./project/handlers.md): handler registry、继承、执行顺序、AI filter/transform 与 trace
- [`project/formatting.md`](./project/formatting.md): `EntryTextFormatter`、`MessageComponentSorter` 与平台兼容顺序
- [`project/knowledge.md`](./project/knowledge.md): RSSHub Routes 知识库同步、manifest diff、任务状态与 source adapter
- [`project/roadmap.md`](./project/roadmap.md): 当前状态与后续演进方向

### dev

- [`dev/setup.md`](./dev/setup.md): 环境准备、运行入口、目录约束
- [`dev/testing.md`](./dev/testing.md): lint、pytest、回归清单
- [`dev/contributing.md`](./dev/contributing.md): 贡献流程、改动边界、提交约定
- [`dev/engineering-principles.md`](./dev/engineering-principles.md): 工具使用、错误处理、保护逻辑与前端验证原则
- [`dev/maintenance.md`](./dev/maintenance.md): 维护规则、配置边界、已移除能力与文档同步要求

### usage

- [`usage/README.md`](./usage/README.md): 使用文档索引
- [`usage/commands.md`](./usage/commands.md): 聊天命令、配置继承、帮助和测试推送
- [`usage/configuration.md`](./usage/configuration.md): 启动级配置、媒体配置、发送策略和 Routes 知识库配置
- [`usage/plugin-pages.md`](./usage/plugin-pages.md): Plugin Pages 管理界面功能边界和操作说明
- [`usage/ai-tools.md`](./usage/ai-tools.md): LLM tools 能力和使用边界
- [`usage/compatibility.md`](./usage/compatibility.md): RSS 解析、媒体发送、平台差异和升级兼容

## 推荐阅读路径

### 我想快速理解这个插件

1. [`project/overview.md`](./project/overview.md)
2. [`project/architecture.md`](./project/architecture.md)
3. 按需继续阅读 `project/` 下的模块章节
4. [`README.md`](../README.md)

### 我要参与开发或维护

1. [`dev/setup.md`](./dev/setup.md)
2. [`dev/testing.md`](./dev/testing.md)
3. [`dev/contributing.md`](./dev/contributing.md)
4. [`dev/engineering-principles.md`](./dev/engineering-principles.md)
5. [`dev/maintenance.md`](./dev/maintenance.md)

### 我只想查命令和配置

1. [`usage/commands.md`](./usage/commands.md)
2. [`usage/configuration.md`](./usage/configuration.md)
3. 按需继续阅读 [`usage/`](./usage/README.md)

## 文档状态

- `project/`: 已升级为章节型架构文档，覆盖核心链路与主要模块
- `dev/`: 本轮已完成
- `usage/`: 已拆分命令、配置、管理页、AI tools 和兼容性说明
