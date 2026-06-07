# AI Tools

在 AstrBot 的 LLM 配置中开启工具调用后，本插件会向 AI 暴露 RSS 订阅与推送相关工具。

## 工具列表

- `rss_subscribe`: 订阅已确认的 RSS/Atom Feed 或 RSSHub 路由；公开参数仍只有 `targets: string[]`。
- `rss_unsubscribe`: 取消当前会话订阅；用户不知道 ID 时先用 `rss_list_subscriptions` 定位。
- `rss_unsubscribe_all`: 取消当前会话全部订阅；`scope=global` 只用于明确的全局清理。
- `rss_list_subscriptions`: 列出当前会话订阅，修改或退订前优先调用。
- `rss_set_subscription_option`: 设置单个订阅选项。
- `rss_set_user_default_option`: 设置用户默认选项。
- `rss_set_session_default_option`: 设置当前会话的新订阅默认选项。
- `rss_get_session_defaults`: 获取当前会话默认配置。
- `rss_list_handlers` / `rss_get_handlers` / `rss_set_subscription_handlers` / `rss_set_user_handlers`: 管理长期 AI 过滤、总结和改写 handlers。
- `rss_list_push_history`: 查询当前会话推送历史，用于排查 `status`、`fail_reason`、`handler_trace`、`raw_xml` 和媒体。
- `rss_push_xml_entry`: 一次性解析 XML/HTML 标签内容并推送到当前会话。

RSSHub 路由检索后续走 AstrBot 知识库和 route skill；插件不再提供 route 搜索 LLM tool。

## Agent 推荐顺序

- 订阅或退订前，如果用户没有给出明确 ID，先调用 `rss_list_subscriptions`。
- 只改一个订阅时用 `rss_set_subscription_option`；改用户长期默认值用 `rss_set_user_default_option`；改当前会话新订阅默认值用 `rss_set_session_default_option`。
- 用户要求“以后过滤 / 总结 / 改写这类推送”时，优先配置 handlers；只做临时分析时不要写入 handlers。
- 排查没推送、发送失败或 AI 过滤行为时，先查 `rss_list_push_history`，再按需读取 handlers。
- `rss_push_xml_entry` 只用于一次性直推，不创建长期订阅，也不读取或注入订阅 handlers。

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
