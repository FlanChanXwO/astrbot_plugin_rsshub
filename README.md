# astrbot_plugin_rsshub

AstrBot RSS 订阅插件，基于 `RSS-to-Telegram-Bot` 迁移并适配 AstrBot 多平台消息发送。

> 新开发者请先阅读贡献指南：[`CONTRIBUTE.md`](./CONTRIBUTE.md)

## 当前能力

- RSS/Atom 订阅、取消订阅、订阅列表
- 订阅级/会话级 interval 调度（同一 feed 在不同会话可使用不同检查间隔）
- 基于 HTML 结构解析内容（链接、图片、音频、视频、文件、At 组件等）
- 订阅级与用户默认级的消息格式选项
- 会话级默认配置（KV）
- LLM 工具调用（除 `sub_test` 外）
- 可选 aiohttp WebUI 管理界面
- 对外请求代码集中在 `api/`（`web/`、`utils/` 保留兼容转发层）

## 命令

- `/sub <RSS链接> [目标]`: 新增订阅，目标可选 `private`/`group`/`current`/完整 session
- `/sub_bind <目标>`: 绑定当前用户默认推送目标
- `/unsub <订阅ID>`: 删除单个订阅
- `/unsub_all [global]`: 删除订阅；默认仅清除当前会话，`global` 清除所有会话（需管理员）
- `/sub_list [all]`: 查看当前用户订阅列表（管理员可用 `all` 查看所有会话）
- `/sub_set <订阅ID> <选项> <值>`: 设置单个订阅选项（支持 `target_session`）
- `/sub_set_default <选项> <值>`: 设置用户默认选项
- `/sub_session_default_set <key> <value>`: 设置会话级订阅默认项（新订阅自动继承）
- `/sub_session_default_get`: 查看当前会话默认项
- `/rss_conf [key] [value]`: 查看/设置插件级配置（`proxy/rsshub_base_url/default_interval/minimal_interval/timeout`）
- `/sub_test <订阅ID> [...]`: 管理员手动触发测试推送
- `/rsshelp`: 查看帮助

## 可配置选项

- 订阅级选项：`notify/send_mode/length_limit/link_preview/display_author/display_via/display_title/display_entry_tags/style/display_media/interval/title/tags/target_session`
- 用户默认选项：`notify/send_mode/length_limit/link_preview/display_author/display_via/display_title/display_entry_tags/style/display_media/interval`
- 会话默认选项：`notify/send_mode/length_limit/link_preview/display_author/display_via/display_title/display_entry_tags/style/display_media/interval/title/tags`

## LLM 工具

- `rss_subscribe`
- `rss_unsubscribe`
- `rss_unsubscribe_all`
- `rss_list_subscriptions`
- `rss_set_subscription_option`
- `rss_set_user_default_option`
- `rss_bind_default_target`
- `rss_get_plugin_config`
- `rss_set_plugin_config`
- `rss_set_session_default_option`
- `rss_get_session_defaults`
- `rsshub_search_routes`（支持可选 `base_url` 覆盖默认域名）
- `rsshub_get_route_schema`（支持可选 `base_url` 覆盖默认域名）
- `rsshub_build_subscribe_url`（输入 `uri + params_json`，支持可选 `base_url`）

以上 RSSHub 相关工具均会返回 `resolved_base_url` 字段，表示本次请求实际使用的域名。

## WebUI

- 在插件配置 `webui.enabled=true` 后自动启动
- 默认地址：`http://0.0.0.0:9191`
- 主要接口：
  - `GET /` 页面
  - `POST /api/login`
  - `GET /api/subscriptions`
  - `PATCH /api/subscriptions/{sub_id}`
  - `DELETE /api/subscriptions/{sub_id}`

## 调度说明

- 调度粒度是订阅（Sub），不是 Feed。
- 同一 feed 可能有多个订阅，各订阅按自己的生效 interval 进入调度。
- 同一分钟内同一 feed 的多个到期订阅只抓取一次，然后分发给对应订阅。
