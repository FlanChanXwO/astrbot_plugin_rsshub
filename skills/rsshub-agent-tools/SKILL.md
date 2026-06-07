---
name: rsshub-agent-tools
description: 使用 astrbot_plugin_rsshub 的 LLM tools 完成 RSS/RSSHub 订阅、退订、配置修改、handlers 管理、push history 排查和 XML/HTML 直推。用户提到订阅、RSSHub route、feed URL、handlers、AI 过滤/总结/改写、raw_xml、push history 或希望 agent 代操作插件时优先使用。
---

# RSSHub Agent Tools

这个 skill 指导 agent 正确调用本插件暴露的 LLM tools。目标是完成真实配置和推送动作，而不是只给用户文字建议。

## 工具边界

插件工具：

- `rss_subscribe`: 订阅已确认的 RSS/Atom Feed 或 RSSHub 路由，唯一公开参数是 `targets: string[]`。
- `rss_unsubscribe`: 按订阅 ID 或 URL 取消当前会话订阅。
- `rss_unsubscribe_all`: 取消当前会话全部订阅；`scope=global` 只在用户明确要求全局清理且具备权限时使用。
- `rss_list_subscriptions`: 查看当前会话订阅列表；退订、修改订阅配置、设置订阅级 handlers 前优先调用。
- `rss_set_subscription_option`: 修改单个订阅配置。
- `rss_set_user_default_option`: 修改用户默认配置，影响该用户后续继承默认值的订阅。
- `rss_set_session_default_option`: 修改当前会话的新订阅默认配置，不修改既有订阅。
- `rss_get_session_defaults`: 查看当前会话默认配置。
- `rss_list_handlers`: 查看可用 handler schema；当前可执行内置 handler 是 `ai_filter` 和 `ai_transform`。
- `rss_get_handlers`: 查看用户默认或某个订阅的 handlers。
- `rss_set_subscription_handlers`: 给单个订阅设置长期 AI 过滤/改写 handlers。
- `rss_set_user_handlers`: 给用户默认设置长期 AI 过滤/改写 handlers。
- `rss_list_push_history`: 查看当前会话推送历史，用于排查 `status`、`fail_reason`、`handler_trace`、`raw_xml`、`media_urls`。
- `rss_push_xml_entry`: 一次性解析 XML/HTML 并推送到当前会话；支持 `dry_run`，不创建长期订阅，也不注入 handlers。

外部能力：

- `astr_kb_search`: 查询 RSSHub Routes 知识库，确认 route、参数和示例。它不负责订阅。
- `future_task`: 用于没有现成 RSS/RSSHub route 的长期网页采集任务。它不是插件订阅。

## 决策流程

订阅任务：

1. 用户给出完整 RSS/Atom URL 或已确认 RSSHub route 时，调用 `rss_subscribe(targets=[...])`。
2. 用户只问“某站怎么订阅 / 有没有 route”时，先用 `astr_kb_search` 查 RSSHub Routes 知识库，不要猜 route。
3. 用户要退订但不知道 ID 时，先 `rss_list_subscriptions`，再 `rss_unsubscribe`。
4. 普通网页没有 RSS 源时，不要硬套 `rss_subscribe`；确认无可用 route 后再考虑 `future_task`。

配置任务：

1. “只改这个订阅” -> 先确认 `sub_id`，再 `rss_set_subscription_option`。
2. “我以后默认都这样” -> `rss_set_user_default_option`。
3. “这个群/会话里以后新订阅默认这样” -> `rss_set_session_default_option`。
4. 修改会话默认值前可先 `rss_get_session_defaults`。

AI 内容处理：

1. 用户要求长期过滤、总结或改写某类推送时，优先落到 handlers 配置。
2. 先 `rss_list_handlers` 查看 schema，再 `rss_get_handlers` 看现状。
3. 单订阅生效用 `rss_set_subscription_handlers`；用户默认生效用 `rss_set_user_handlers`。
4. 只允许按 schema 生成 `ai_filter` / `ai_transform`，不要编造 handler 名称。

排障：

1. 用户问“为什么没发 / 为什么被过滤 / 为什么失败”时，先 `rss_list_push_history(page="1", page_size="20")`。
2. 重点看 `status`、`fail_reason`、`handler_trace`、`raw_xml`、`media_urls`。
3. 如果是 handler 行为，再 `rss_get_handlers` 检查当前配置。

XML/HTML 直推：

1. 用户提供 XML/HTML 片段并要求发到当前会话时，调用 `rss_push_xml_entry`。
2. 内容复杂或用户要预览时，先传 `dry_run=true`。
3. dry run 成功后再正式发送。

## handlers JSON 模板

AI 过滤：

```json
[
  {
    "id": "builtin.ai_filter.default",
    "type": "builtin",
    "name": "ai_filter",
    "status": 1,
    "config": {
      "prompt": "过滤掉广告、抽奖、无信息量转发",
      "input_scope": "both",
      "reason_max_length": 120
    }
  }
]
```

AI 总结/改写：

```json
[
  {
    "id": "builtin.ai_transform.default",
    "type": "builtin",
    "name": "ai_transform",
    "status": 1,
    "config": {
      "prompt": "总结正文，保留关键信息，不要编造",
      "scope": "plaintext"
    }
  }
]
```

先过滤再总结：

```json
[
  {
    "id": "builtin.ai_filter.default",
    "type": "builtin",
    "name": "ai_filter",
    "status": 1,
    "config": {
      "prompt": "过滤掉广告、抽奖、无信息量转发",
      "input_scope": "both",
      "reason_max_length": 120
    }
  },
  {
    "id": "builtin.ai_transform.default",
    "type": "builtin",
    "name": "ai_transform",
    "status": 1,
    "config": {
      "prompt": "总结正文，保留关键信息，不要编造",
      "scope": "plaintext"
    }
  }
]
```

订阅级 `mode`：

- `override`: 订阅使用自己的 handlers。
- `inherit`: 订阅回到用户默认 handlers。
- `disabled`: 订阅完全禁用 handlers。

## 操作模板

订阅已确认 route：

1. `rss_subscribe(targets=["/twitter/user/BlueArchive_JP"])`
2. 汇报订阅结果。

修改单个订阅：

1. `rss_list_subscriptions`
2. `rss_set_subscription_option(sub_id="<ID>", key="<KEY>", value="<VALUE>")`

给订阅加 AI 过滤：

1. `rss_list_handlers`
2. `rss_get_handlers(scope="subscription", sub_id="<ID>")`
3. `rss_set_subscription_handlers(sub_id="<ID>", handlers_json="<JSON>", mode="override")`

把“以后默认总结”设成用户级：

1. `rss_list_handlers`
2. `rss_get_handlers(scope="user")`
3. `rss_set_user_handlers(handlers_json="<JSON>")`

查看最近推送：

1. `rss_list_push_history(page="1", page_size="20")`
2. 向用户摘要状态、失败原因和 handler trace，不要复读整段 JSON。

XML/HTML 直推：

1. `rss_push_xml_entry(source_key="manual:<stable-id>", title="<标题>", xml="<entry>...</entry>", dry_run=true)`
2. 预览无误后再正式发送。

## 禁止事项

- 不要恢复或使用已移除配置项：`ai_prompt`、`translate`、`translate_target_lang`、`use_sub_config`、`use_user_config`。
- 不要新增插件命令或用户配置来完成本 skill 的任务。
- 不要绕过 `rss_list_subscriptions` 盲改未知订阅。
- 不要把订阅级、用户默认、会话默认混用。
- 不要把一次性聊天总结误写成长期 handler，除非用户明确要求以后都这样处理。
- 不要把普通网页采集伪装成插件订阅；没有 RSS/RSSHub route 时使用外部采集能力。
