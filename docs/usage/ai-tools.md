# AI Tools

在 AstrBot 的 LLM 配置中开启工具调用后，本插件会向 AI 暴露 RSS 订阅与推送相关工具。

## 工具列表

- `rss_subscribe`: 订阅 RSS 源；公开参数为 `targets: string[]`，每项可以是完整 Feed URL、RSSHub 路径或路由路径。
- `rss_unsubscribe`: 取消订阅。
- `rss_unsubscribe_all`: 取消所有订阅。
- `rss_list_subscriptions`: 列出订阅。
- `rss_set_subscription_option`: 设置订阅选项。
- `rss_set_user_default_option`: 设置用户默认选项。
- `rss_set_session_default_option`: 设置会话默认选项。
- `rss_get_session_defaults`: 获取会话默认配置。
- `rss_list_push_history`: 查询当前会话推送历史。
- `rss_push_xml_entry`: 解析 XML/HTML 标签内容并推送到当前会话。

RSSHub 路由检索后续走 AstrBot 知识库和 route skill；插件不再提供 route 搜索 LLM tool。

## XML 即时推送

`rss_push_xml_entry` 面向 AI agent 的即时推送工具，不使用订阅 `sub_id`，也不读取订阅默认配置。

它会：

- 对输入 XML 做格式校验，拒绝坏格式、DOCTYPE/ENTITY 和超大输入。
- 将标签内容解析为正文与媒体组件。
- 允许安全排版参数：`style`、`send_mode`、`display_media`、`display_title`、`display_author`、`display_via`、`display_entry_tags`、`length_limit`。
- 不开放 `handlers`，即时推送不会让 agent 注入处理链。
- 使用 `source_key + user_id + target_session + entry_guid` 做成功态幂等去重。
- 写入推送历史并复用现有失败重试链路。
- 在媒体发送失败时，把原始媒体链接保留到失败历史和回退文本中。
- 为 XML 即时推送历史额外保存 `raw_xml`，便于审计和排障。

命令仍是新增订阅、导入导出等用户归属流程的兜底入口；Plugin Pages 不提供新增订阅或 TOML 导入导出入口。
