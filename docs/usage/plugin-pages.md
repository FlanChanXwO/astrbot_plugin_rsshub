# Plugin Pages 管理界面

管理界面使用 AstrBot Plugin Pages，通过 AstrBot 面板访问。后端接口由 `WebApiHandler` 注册到 `/{plugin_name}/...` 路径下，当前为 `/astrbot_plugin_rsshub/...`。

## 功能范围

Plugin Pages 提供：

- 左侧导航与独立「概览」页，用于查看总订阅、启用订阅、Feed 源、用户数和健康度图表。
- 订阅、Feed、用户列表管理。
- Bundle 聚合订阅和成员顺序、状态、backlog 管理。
- 卡片模板列表、安装、候选筛选、预览和引用保护删除。
- 推送历史查询、筛选、重试和清理。
- 默认订阅设置。
- 用户/订阅 handler 链编辑。
- RSSHub Routes 知识库状态、初始化和同步任务管理。

Plugin Pages 不创建新订阅，也不提供 TOML 导入导出。新增、导入和导出订阅请使用聊天命令或 AI agent。

## 订阅与 Feed

订阅、用户、Feed 和推送历史页使用紧凑筛选栏。关键词框用于当前列表搜索；需要 ID、URL 或状态等精确条件时，先选择筛选列，输入筛选值，再点击「+」添加为条件 chip。已添加条件可以逐个移除，刷新按钮只保留图标。窄屏下订阅表格会切换为卡片布局，避免按钮或长文本重叠。

Feed 列表支持编辑和删除。删除 Feed 会删除对应订阅；用户、订阅和 Feed 删除时推送历史默认保留，只有在确认中显式选择时才一起删除。

## Bundle 与卡片模板

Bundle 页面只管理已有 Feed 成员，不在 Pages 创建 Bundle 或发现新 Feed。详情页展示成员 position、最近采集状态、未认领 backlog 和 pending batch；移除成员或删除 Bundle 遇到已认领/未认领输入时会显示机器可读的阻塞详情。

卡片模板页展示内置和已安装包的 metadata。Subscription/Bundle 编辑侧栏只显示通过 owner 匹配校验的候选模板，并提供 `send_card`、`card_send_original_content` 和非持久化预览。模板预览会运行当前 handler，但不修改水位、inbox、batch 或 history；模板删除前会检查活动引用。

## 概览图表

概览页提供三类只读图表：Feed 新鲜度、推送成功率和 Feed 订阅占比。时间范围固定为 24 小时、1 周和 1 个月，默认 1 周。

Feed 新鲜度按最近一次成功解析保存时间与订阅监控间隔分档；推送成功率按 `success / (success + failed)` 计算，`stopped` / `skipped` / `pending` / `retrying` 只作为参考计数或积压参考；Feed 订阅占比展示 Top 8，其余合并为「其他」。图表库作为本地静态资源随插件提供，不依赖 CDN。

## 用户与默认设置

用户列表展示总订阅数和启用订阅数。用户状态只保留「用户」和「已封禁」两种。

默认订阅设置统一使用底部保存按钮。订阅默认值不再在 AstrBot 配置页暴露。

## 推送历史

推送历史可按 Feed URL 筛选，并按最近活动时间排序。

每行提供「重试」操作，用于人工重放旧记录。重试会复用原记录保存的文本、媒体 URL、目标会话和来源信息，并把本次结果写回原历史行。

历史详情会分别展示 handler 前的「输入 XML」和处理后的「输出 XML」。Subscription card 包含多条输入时，输入区域显示带 `item_key` 的 XML 列表；旧历史没有输入快照时显示为空，不把输出 XML 冒充输入。

点击历史行跳转相关订阅时，会按历史保存的 Feed 链接和用户精确筛选，不使用历史 `sub_id`，避免订阅删除后自增 ID 被新订阅复用造成误匹配。

## Handler 编辑

用户/订阅处理链编辑器优先读取 Web API `handlers/schema`，并在接口不可用时使用内置 fallback。当前支持启停、排序、添加内置 handler、删除、schema 字段编辑和原始 JSON 高级模式。

旧版内置翻译、AI enrich 管道已移除。当前 handler 主要面向 `ai_filter` 与 `ai_transform`。
