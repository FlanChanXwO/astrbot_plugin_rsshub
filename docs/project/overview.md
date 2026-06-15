# 项目概览

## 插件定位

`astrbot_plugin_rsshub` 是一个面向 AstrBot 的 RSS/RSSHub 订阅插件。它的核心职责不是“做所有内容处理”，而是提供一条稳定的订阅基础设施链路：

- 管理订阅、用户默认配置和会话默认配置
- 定时抓取 Feed，完成去重、调度和失败重试
- 将解析后的文本与媒体发送到不同平台
- 记录推送历史，支持重试、过滤、审计与管理页排障
- 为 AstrBot 的 AI agent 提供订阅管理和 XML 即时推送工具

## 为什么保持这个定位

这个插件已经经历过“功能不断往里塞”的阶段，历史上出现过几类问题：

- 翻译、总结、格式化、路由检索、推送可靠性混在同一条链里
- 用户界面、命令、配置模型和运行时行为容易脱节
- 一处内容处理改动会顺带影响推送历史、去重或 sender 兼容性

当前定位的目标，是把最容易回归、最需要稳定的部分单独保护出来：

1. **订阅基础设施稳定**
   - Feed 抓取
   - 去重
   - 调度
   - 发送
   - 审计
2. **内容处理可替换**
   - 通过 handlers 链串接
   - AI 失败时默认放行，不阻断 RSS
3. **管理路径清晰**
   - 命令处理用户拥有的数据入口
   - Plugin Pages 负责已有数据的管理、排障和可视化
   - AI tools 负责自动化编排

## 当前能力边界

### 插件负责

- Feed 抓取、去重、调度和推送
- 用户/订阅/推送历史持久化
- Plugin Pages 管理界面
- 多平台 sender 适配
- 内置 content handlers:
  - `ai_filter`
  - `ai_transform`
- RSSHub Routes 知识库同步入口

### 插件不再负责

- 旧版内置翻译管道
- 独立的 AI enrich / summarize 配置面板
- RSSHub route 搜索型 LLM tool
- WebUI 中的新建订阅、导入订阅、导出订阅入口

这些能力要么已经移除，要么收敛到 handlers、AstrBot 知识库工具、聊天命令或后续扩展运行时。

## 当前用户入口

插件当前主要通过三类入口使用：

1. 聊天命令
   - `/sub`
   - `/unsub`
   - `/sub_list`
   - `/sub_profile`
   - `/sub_session`
   - `/sub_test`
2. AI tools
   - 订阅管理
   - 会话默认值读取
   - XML 即时推送
   - handler 读写
3. Plugin Pages
   - 订阅、用户、Feed、推送历史、处理器、知识库、默认设置、数据管理

## 当前实现取向

这个项目在 v2.0.0 阶段的取向可以概括为三点：

1. 把“可靠发送”放在第一优先级。
2. 把“内容加工”收敛到 handler 链，而不是散落在多个旧配置里。
3. 把“可管理性”前移到 Plugin Pages 和 push history。

## 为什么保留 DDD 分层

这里继续保留 DDD 分层，不是为了形式，而是因为这个插件天然有多类变化频率完全不同的东西：

- 领域规则：订阅、用户、push history、继承值、handler spec
- 用例编排：订阅、取消订阅、测试推送、批量操作
- 基础设施细节：SQLite、AstrBot config、平台 sender、KB source
- 外部接口：聊天命令、Web API、LLM tools、Plugin Pages

如果把这些混在一起，最直接的后果是：

- 配置兼容代码污染核心业务
- sender 平台差异反向侵入订阅逻辑
- Web API 和命令实现各自维护一套行为

当前分层结构的价值在于：

- `domain` 保护稳定语义
- `application` 收口用例
- `infrastructure` 吞掉 AstrBot / 平台 / 存储差异
- `interfaces` 只负责入口适配

这让“修一个推送 bug”不需要顺带碰 UI、命令和配置加载。

## 为什么保留 handlers

旧版内容处理曾经散落在：

- 配置项
- formatter
- polling service
- 独立过滤器

现在统一收口到 handlers，原因很直接：

- 能记录 trace
- 能挂在订阅/用户配置上
- 能清楚表达顺序
- 能让 AI 行为变成受控步骤，而不是隐含副作用

这比把 AI 逻辑塞进 formatter 或 polling service 更容易维护。

## 为什么保留 Plugin Pages

这个插件的数据量和排障需求已经超过“只靠命令输出文本”的阶段。Plugin Pages 的价值在于：

- 让 push history、handler trace、失败原因可见
- 让用户/Feed/订阅/知识库状态能够联动查看
- 让默认配置、缓存与导出文件可管理

但它不承担“创建新订阅”这种带用户归属语义的入口，避免和命令/AI tool 重复维护。

## 为什么 push history 是架构中心之一

`push_history` 不只是日志表，它承担三件事：

1. 审计：到底发了什么、为什么被跳过、失败在哪
2. 幂等：成功态去重与 agent push 范围去重
3. 重试：失败后保留可恢复上下文

所以当前很多设计都围绕它做了让步：

- `content` 必须保存最终可发送文本
- `raw_xml` 保留原始条目
- `handler_trace` 只记录执行摘要，不泄漏 provider 内部 prompt
- 媒体失败时追加原始链接到失败侧文本

## 对维护者最重要的事实

本页只保留定位与取舍，不维护细节清单。修改前按主题查对应章节：

- 启动、分层、配置职责：[`architecture.md`](./architecture.md)
- 领域值、配置模型、常量归属：[`domain-model.md`](./domain-model.md)
- 命令、AI tools、用户配置、推送历史：[`application.md`](./application.md)
- 平台发送、媒体、代理、缓存：[`platforms.md`](./platforms.md)
- 分发、失败重试、去重审计：[`dispatch.md`](./dispatch.md)
