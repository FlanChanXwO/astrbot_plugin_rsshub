# 应用层入口与行为边界

本文记录应用层入口、聊天命令、AI tools、订阅配置与推送历史的稳定语义。它面向需要修改 `src/application/`、`src/interfaces/` 或入口编排的维护者。

> [!IMPORTANT]
> 应用层只描述入口语义和用例边界。领域值细节看 [`domain-model.md`](./domain-model.md)，平台发送差异看 [`platforms.md`](./platforms.md)。

## 聊天命令边界

以下命令需要保持完整参数签名，兼容 `GreedyStr` 风格参数。

| 命令 | 当前行为 | 不要回退 |
| --- | --- | --- |
| `/sub` | 支持多个 URL 批量订阅。 | 不要退回单 URL 语义。 |
| `/unsub` | 支持 ID 和 URL 混合批量取消。 | 不要只支持单 ID。 |
| `/sub_list` | 只展示当前会话订阅，支持分页。 | 不恢复 `all` 范围。 |
| `/sub_export [all]` | 保留管理员校验。 | 不绕过 admin guard。 |
| `/sub_import` | 支持 TOML 路径和上传等待流程。 | 不要移除上传等待监听。 |
| `/sub_test <ID\|URL>` | 真实推送最新条目，不是预览；聊天命令不接受额外范围参数。 | 不要恢复“测试推送未进入正式链路”的泛化误判。 |
| `/sub_status` | 展示当前会话运行中或排队中的推送任务。 | 不把全局队列无筛选暴露给普通用户。 |
| `/sub_stop [job_id\|feed_id\|all]` | 支持精确停止和批量停止；无参数时停止当前运行任务。 | 不让停止语义绕过审计。 |
| `/bundle` / `/聚合订阅` | 支持 `create/list/show/add/remove/move/set/state/test/retry/discard/delete`；名称支持引号，成员和配置修改由 Bundle 应用用例统一校验。 | 不在命令入口复制归属、模板或可靠投递保护规则；`test` 仅管理员可用且不写正常业务批次。 |
| `/rsshelp` | 发送预生成帮助图；按 AstrBot `timezone` 选择日间/夜间主题，读不到或时区非法时回退系统本地时间。 | 不把帮助图生成放到运行时热路径。 |
| `/rsshub_kb_init` / `/rsshub_kb_sync` / `/rsshub_kb_status` / `/rsshub_kb_task` | 管理 RSSHub Routes 知识库同步。 | 不恢复 route-search / route-build LLM tools。 |

命令解析细节见 [`commands.md`](./commands.md)。

## AI tools 边界

| Tool / 能力 | 输入边界 | 输出 / 副作用 | 备注 |
| --- | --- | --- | --- |
| `rss_subscribe` | 只暴露 `targets: string[]` | 批量订阅目标 | `targets` 中每项可以是完整 Feed URL、RSSHub path 或 route path。 |
| `rss_push_xml_entry` | 只暴露安全格式化参数，如 `style`、`send_mode`、显示选项、`length_limit` | 立即推送 XML/HTML 条目并写入 `push_history` | 不暴露 `handlers`，避免即时推送注入处理链。 |
| `rss_bundle_*` | 只使用当前事件用户；公开 create/list/get/update_members/set_option/set_handlers/set_state/delete | 管理当前用户 Bundle | 不暴露 test/retry/discard；成员、模板和删除保护复用 Bundle 应用用例。 |
| XML payload 校验 | 拒绝 malformed、超大、DOCTYPE 输入 | 失败时不进入发送链路 | 保护 XML 解析和后续 handler。 |
| agent push 去重 | `(source_type, source_key, user_id, target_session, entry_guid)` | 只看成功态 | 不依赖公开 `sub_id`。 |
| agent retry | 复用历史记录中的 target 和 media 上下文 | 直接重发 | 保留审计连续性。 |

`src/application/llmtools/` 按订阅、配置、handlers、历史和 XML 直推拆分工具实现；公开入口仍是 `build_llm_tools` 与 `LLM_TOOL_NAMES`。这次拆分只改变代码组织和工具说明，不改变公开参数 schema。

## 订阅、用户与历史语义

### Bundle 成员采集

Bundle 的成员由 `BundleFeed.position` 定义稳定顺序，采集由 `BundleCollectionService` 逐成员串行执行。每个成员独立保存 ETag、Last-Modified、条目指纹和最近检查状态；相同 Feed 被多个消费者引用时不共享这些私有水位。

成功发现和对应成员水位通过可靠投递仓储在同一事务写入通用 inbox。首次成功 200 遵循全局 `bootstrap_skip_history`：开启时只初始化水位，关闭时把当前响应的新增条目完整入箱；首次 304、抓取/解析失败或事务回滚都不会初始化成员。单成员失败会记录状态并继续后续成员。

### Bundle 聚合文档

`BundleDocumentService` 在批次认领后按成员 `position` 构造 RSS 2.0 文档：成员内有发布时间的条目按发布时间降序排列，无时间条目保留抓取顺序；`history_entry_limit` 只作用于每个成员，不设置 Bundle 总量上限。builder 使用结构化 XML API 写入来源、媒体、作者、标签和转义后的内容，并由 `BundleRssDocumentValidator` 校验文档结构。

Bundle 的 `ai_filter` 与 `ai_transform` 在完整 channel 上运行，和现有 entry handler 使用独立输入契约。provider 不可用、非法 JSON/XML 或 handler 异常会记录文档级 trace 并保留上一步快照；过滤拒绝只改变输出允许状态。`consumption_item_keys` 始终来自原始 inbox 条目，不能从 handler 改写后的 XML 反推，后续批次确认或丢弃据此消费原始输入。

### Bundle 可靠投递与调度

`BundleBatchDeliveryService` 以 `(owner_type=bundle, owner_id)` 为并发边界：先恢复并 reconciliation 现有 pending 批次，再从未认领 inbox 创建一个新批次。文档生成后只认领本批实际消费的 `item_key`，因此成员级 `history_entry_limit` 留下的 backlog 会进入后续批次；批次中的 document、template、send payload 和 Feed 上下文均为不可变快照。

`OutputOrchestrator` 对每个目标会话按 `card → standard` 编排：卡片失败、停止或未确认时不会发送同批 standard；卡片成功或规则性 skip 后才发送 standard。发送成功、规则性 skip、失败、取消停止、自动重试和显式 discard 都通过可靠投递仓储更新 history、batch 与 inbox。进程可能在发送后、confirm 前退出，下一次推进会先 reconciliation，已确认或已丢弃的历史批次不会被重新发送。

`RSSScheduler` 每轮先处理到期 Bundle 成员采集，再推进 Bundle 批次重试，并将 `next_check_time` 沿原滚动计划推进到首个未来周期；采集失败不会阻止后续 Bundle 或普通 Subscription。运行时 bootstrap 为 Bundle 单独实例化文档服务、输出执行器和批次服务，同时复用共享的 history/delivery 仓储。

| 主题 | 当前语义 | 备注 |
| --- | --- | --- |
| 配置继承 | 订阅继承用户，用户继承全局默认；继承值只认 `-100` | 不恢复 `use_sub_config` / `use_user_config`。 |
| Handler 链 | `rsshub_sub.handlers` 与 `rsshub_user.handlers` 保存 JSON handler 链 | 旧非空 `ai_prompt` 迁移为 `builtin.ai_transform`。 |
| 旧翻译字段 | `translate`、`translate_target_lang` 保持移除 | 翻译不再是应用层内置入口。 |
| `minimal_interval` | 写入阶段硬下限 | 不要降级成运行时临时 clamp。 |
| 用户事实表 | 写入订阅或推送历史前必须确保非空 `user_id` 有用户记录 | 启动自愈会从订阅和历史补齐缺失用户。 |
| 删除用户 | 默认删除用户和该用户全部订阅 | 推送历史默认保留，显式 `delete_push_history=true` 才删除。 |

## 推送历史与重试

| 行为 | 当前语义 | 备注 |
| --- | --- | --- |
| `PushHistory.fail_reason` | 必须保持在模型和数据库限制内，当前上限为 512 字符 | 仓储读取历史脏数据时要能截断过长失败原因。 |
| `failed_queue_capacity=0` | 只关闭自动失败队列捞取 | 不影响失败历史写入和保留。 |
| `failed_queue_max_retries` | 只控制自动重试次数上限 | 不代表可以删除失败历史。 |
| Plugin Pages 手动重试 | 复用同一条 `push_history`，更新结果和最近活动时间 | 不新增历史行，不消耗自动重试次数。 |
| `deduplicate_multi_bot` | 只在同一 `target_session` 且最终 payload 等价时去重 | 被压制的发送必须写入 `status=skipped`。 |
| 规则性跳过 | handler deny、通知关闭、成功去重 guard、多 BOT 去重都写入 `status=skipped` | 这类 skipped 是可审计 ack；不能伪装成 success。 |
| Feed 水位确认 | 只有 `success` 或明确规则性 `skipped` 会确认本轮新 entry | `pending`、`failed` 或分发异常不能推进 `entry_hashes` / 条件请求水位，避免漏推。 |

## 已移除的应用能力

| 能力 | 当前状态 | 替代路径 |
| --- | --- | --- |
| route-search / route-build LLM tools | 不恢复 | 路由检索走 AstrBot KB；订阅走 `rss_subscribe(targets=[...])`。 |
| 旧翻译管道入口 | 不恢复 | 后续内容加工归 handler / AI transform / 扩展运行时。 |
| 旧 AI enrich / summarize 配置入口 | 不恢复 | 统一收敛到 handler chain。 |
| Plugin Pages 新建订阅、TOML 导入、TOML 导出 | 不恢复 | 用户归属流程保留在聊天命令或 AI tools。 |
