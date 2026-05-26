# 项目文档

本目录用于说明插件是什么、为什么这样设计、当前做到什么程度，以及后续准备往哪里走。

## 目录

- [`overview.md`](./overview.md): 项目定位、能力边界、核心特性
- [`architecture.md`](./architecture.md): 架构全景、设计理由、核心模块关系
- [`domain-model.md`](./domain-model.md): 领域值、枚举语义、配置模型与常量归属
- [`application.md`](./application.md): 应用层入口、命令边界、AI tools、用户配置与推送历史语义
- [`polling.md`](./polling.md): Feed 轮询、去重、增量识别与 dispatch 输入构造
- [`dispatch.md`](./dispatch.md): 推送分发、history 语义、失败重试与 sender 入口
- [`platforms.md`](./platforms.md): 平台发送差异、媒体预下载、代理、缓存与常量放置规则
- [`commands.md`](./commands.md): 订阅命令链、测试推送与完整入口分支
- [`web_api.md`](./web_api.md): Dashboard 的 HTTP 数据面、筛选和管理接口
- [`repositories.md`](./repositories.md): 仓储层、ORM 适配和查询/幂等细节
- [`sender.md`](./sender.md): NotificationService、sender adapter 与媒体 fingerprint
- [`handlers.md`](./handlers.md): handler registry、继承、AI filter/transform 行为
- [`formatting.md`](./formatting.md): 文本格式化、媒体组件排序与平台兼容策略
- [`knowledge.md`](./knowledge.md): RSSHub Routes 知识库同步、manifest diff 与任务状态
- [`roadmap.md`](./roadmap.md): 当前版本状态与后续演进方向

## 职责边界

- `overview.md` 解释“为什么是这个插件形态”，不承载细节规则。
- `architecture.md` 解释“模块如何连接”，不复制各模块算法。
- `domain-model.md` 维护跨模块稳定值和配置模型归属。
- `application.md` 维护入口语义和应用层行为边界。
- `polling.md`、`dispatch.md`、`handlers.md`、`formatting.md`、`sender.md`、`platforms.md`、`web_api.md`、`repositories.md`、`knowledge.md` 分别维护各自模块流程。
- `roadmap.md` 只记录当前阶段和演进方向，不作为行为契约。

## 适合谁看

- 第一次接手这个插件的维护者
- 需要了解当前实现边界的协作者
- 准备规划新功能或排查架构问题的人

## 推荐阅读顺序

1. [`overview.md`](./overview.md)
2. [`architecture.md`](./architecture.md)
3. 按需阅读各模块深挖文档
