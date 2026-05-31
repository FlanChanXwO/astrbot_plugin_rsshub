# Plugin Pages 管理界面

管理界面使用 AstrBot Plugin Pages，通过 AstrBot 面板访问。后端接口由 `WebApiHandler` 注册到 `/{plugin_name}/...` 路径下，当前为 `/astrbot_plugin_rsshub/...`。

## 功能范围

Plugin Pages 提供：

- 订阅、Feed、用户列表管理。
- 推送历史查询、筛选、重试和清理。
- 默认订阅设置。
- 用户/订阅 handler 链编辑。
- RSSHub Routes 知识库状态、初始化和同步任务管理。

Plugin Pages 不创建新订阅，也不提供 TOML 导入导出。新增、导入和导出订阅请使用聊天命令或 AI agent。

## 订阅与 Feed

订阅列表提供 Feed URL 筛选入口，筛选框使用标签输入，按 Enter 提交一个筛选值。窄屏下订阅表格会切换为卡片布局，避免按钮或长文本重叠。

Feed 列表支持编辑和删除。删除 Feed 会删除对应订阅；用户、订阅和 Feed 删除时推送历史默认保留，只有在确认中显式选择时才一起删除。

## 用户与默认设置

用户列表展示总订阅数和启用订阅数。用户状态只保留「用户」和「已封禁」两种。

默认订阅设置统一使用底部保存按钮。订阅默认值不再在 AstrBot 配置页暴露。

## 推送历史

推送历史可按 Feed URL 筛选，并按最近活动时间排序。

每行提供「重试」操作，用于人工重放旧记录。重试会复用原记录保存的文本、媒体 URL、目标会话和来源信息，并把本次结果写回原历史行。

点击历史行跳转相关订阅时，会按历史保存的 Feed 链接和用户精确筛选，不使用历史 `sub_id`，避免订阅删除后自增 ID 被新订阅复用造成误匹配。

## Handler 编辑

用户/订阅处理链编辑器优先读取 Web API `handlers/schema`，并在接口不可用时使用内置 fallback。当前支持启停、排序、添加内置 handler、删除、schema 字段编辑和原始 JSON 高级模式。

旧版内置翻译、AI enrich 管道已移除。当前 handler 主要面向 `ai_filter` 与 `ai_transform`。
