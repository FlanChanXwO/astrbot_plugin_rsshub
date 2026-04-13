# Changelog

## [1.0.10] - 2026-04-12

### Added

- 新增命令中文别名支持，所有命令现在支持中英文双语调用：
  - `/订阅` → `/sub`
  - `/取消订阅` → `/unsub`
  - `/取消全部订阅` → `/unsub_all`
  - `/订阅列表` → `/sub_list`
  - `/测试订阅` → `/sub_test`
  - `/导出订阅` → `/sub_export`
  - `/导入订阅` → `/sub_import`
  - `/设置订阅` → `/sub_set`
  - `/设置默认订阅` → `/sub_set_default`
  - `/绑定订阅` → `/sub_bind`
  - `/设置会话默认` → `/sub_session_default_set`
  - `/获取会话默认` → `/sub_session_default_get`
  - `/RSS配置` → `/rss_conf`
  - `/失败队列` → `/sub_failed_queue`
  - `/RSS帮助` → `/rsshelp`

### Changed

- 优化订阅导出格式：导出时自动排除 `target_session` 字段（该字段根据当前会话实时计算）
- 增强导入兼容性：检测并忽略导入文件中的 `id`/`sid`/`sub_id` 字段，确保跨 Bot 实例迁移时 ID 正确生成

## [1.0.9] - 2026-04-09

### Added

- 新增单会话多 BOT 去重功能：
  - 配置项 `deduplicate_multi_bot`（默认 true）
  - 当同一会话中有多个 BOT 订阅了相同的 RSS 源，只有最早订阅的 BOT 会推送消息
  - 避免重复推送问题
- 新增平台共享数据源功能：
  - 配置项 `platform_shared_data` 支持按平台开启共享模式
  - 目前支持 `aiocqhttp` 平台
  - 开启后，该平台下所有 BOT 的订阅数据共享
  - 任意 BOT 掉线时，其他 BOT 可继续推送
  - `/sub` `/unsub` `/sub_list` 命令均支持共享模式
- 新增可配置的发送策略：
  - 支持在配置中开启/关闭特定平台的发送策略
  - 新增 `sender_strategies` 配置项，包含 `telegram` 和 `aiocqhttp` 两个子项
  - 新增 `/rss_conf sender_strategy_telegram <true/false>` 命令控制 Telegram 策略
  - 新增 `/rss_conf sender_strategy_aiocqhttp <true/false>` 命令控制 OneBot 策略
  - 关闭特定平台策略后将自动使用默认发送策略

## [1.0.8] - 2026-04-09

### Added

- 新增失败队列机制，解决平台连接断开时的消息丢失问题：
  - 当推送因平台连接失败（如 Bot 被踢下线）时，消息会自动进入失败队列
  - 每分钟监控任务会自动尝试重试失败队列中的消息
  - 支持配置队列容量 `failed_queue_capacity`（默认 50 条/订阅）
  - 新增 `/sub_failed_queue` 命令查看队列状态
  - 新增配置项 `failed_queue_capacity` 可通过 `/rss_conf` 设置

## [1.0.7] - 2026-04-09

### Added

- 新增 `/sub_export` 命令用于导出订阅数据：
  - 默认导出当前用户当前会话的订阅
  - 管理员可使用 `/sub_export all` 导出所有订阅
  - 导出格式为 TOML，与 `/sub_import` 兼容，便于备份和迁移

### Fixed

- `/sub_export` 文件名添加 8 位 UUID 后缀，避免同一秒内多次调用导致文件名冲突
- `/sub_export` 发送文件后自动清理临时文件，防止临时目录无限制增长

## [1.0.6] - 2026-04-08

### Changed

- 调整 `/sub_list` 输出策略为单条纯文本返回，由平台自行处理长消息（如合并转发）
- 将管理员全局列表默认分页收敛为每页 5 条，减少单次查询/展示负载
- 为 aiocqhttp 媒体发送路径新增调试日志：输出 media 来源（url/local_path）及本地文件存在性、大小

### Fixed

- 修复媒体缓存 GC 与缓存写入并发下的误删问题：删除阶段增加过期状态二次校验，避免删除刚刷新的缓存文件
- 优化缓存 GC 锁粒度：采用“扫描无锁 + 删除加锁”两阶段流程，降低高并发下载场景下的锁竞争
- 清理 `/sub_list` 历史分片残留逻辑与无用常量，避免后续维护歧义

## [1.0.5] - 2026-04-07

### Changed

- 调整 `/sub_list all` 为管理员全局视图：展示数据库内所有平台/会话订阅
- 为管理员全局列表新增分页能力：支持 `/sub_list all [page] [page_size]`，避免一次性加载/输出全量数据

### Fixed

- 修复同一 RSS 源在多平台/多会话并发订阅时的推送抢占：单次更新统一扇出到该源全部活跃订阅，避免条目被不同会话分走
- 修复开启“先下载图片再发送”后，aiocqhttp 合并转发路径偶发 `ENOENT`（媒体缓存文件提前删除）的问题
- 修复媒体缓存 GC 与缓存写入并发竞争导致的 `ENOENT`：为缓存 GC/读写引入 I/O 互斥并添加下载后双重检查
- 修复 `rsshelp` 文案中的乱码问题

## [1.0.4] - 2026-04-07

### Changed

- 调整 `AiocqhttpMessageSender` 回退策略为“仅合并转发”：合并转发失败后不再尝试非合并消息链
- 新增 aiocqhttp 合并失败兜底链路：改为发送“纯文本合并节点”，保持推送形态一致

### Fixed

- 修复 aiocqhttp 在合并转发失败时退化为直发文本消息的问题
- 优化违规或受限媒体场景下的降级行为：文本中补充媒体原始链接，降低信息丢失风险

## [1.0.3] - 2026-04-07

### Added

- 新增订阅导入/批量退订辅助模块 `utils/command_helpers.py`，将筛选、导出、删除与导入应用逻辑从命令处理器中拆分，提升维护性
- 新增 Telegram 媒体发送调试信息：记录 `video/audio` 最终来源（`url` 或 `local_path`）并输出哈希，便于排查线上媒体链路问题

### Changed

- 调整 Telegram 发送策略为媒体优先（media-first）：图片/视频/音频优先于文本进入消息链，并在分片回退路径中保持同样顺序
- `RSSHubRadarAPI` 规则缓存改为带容量限制的 `LRU + TTL`（按 `base_url` 键），避免长期运行时缓存无界增长
- `RSSHubRadarAPI` 网络请求/JSON 解析错误信息增强：增加 `base_url`、`url` 与异常类型上下文，提升故障定位效率
- `/unsub_all` 行为明确为“默认当前会话，`global` 全局删除（管理员）”，并移除历史 `yes` 参数语义

### Fixed

- 修复 Telegram 媒体发送 `Wrong http url specified` 问题：在 Telegram 发送前将 `file:///` URI 归一化为本地路径，避免适配器侧误判 URL
- 修复多处中文提示乱码（mojibake），包括路由参数获取失败、默认选项更新提示与测试推送目标提示
- 修复 `AiocqhttpMessageSender` 在媒体回退为纯文本且发送成功时仍标记 `transient=True` 的问题，避免误触发重试逻辑
- 修复导入会话键类型注解与实际值不一致问题，统一使用字符串 sender_id 构造会话键

### Security

- 限制本地路径导入能力：仅管理员可用，且仅允许读取插件数据目录白名单路径下文件，降低越权读取风险

### Docs

- 更新命令文档：`/sub_list [all]` 与实现保持一致；PR 模板与贡献文档文字表述修正并同步

## [1.0.2] - 2026-04-06

### Changed

- 优化 RSS 条目去重指纹生成策略：对链接、文本与时间戳进行规范化处理，并改用基于 SHA-256 的多指纹匹配机制，提高去重稳定性与准确性
- 扩大 Feed 去重历史窗口：跨轮次合并并持久化历史哈希，默认动态保留上限调整为 `min(max(200, entries * 2), 5000)`，并支持配置项覆盖，提升历史重复内容识别能力并控制资源开销

### Fixed

- 修复因哈希输入不稳定与去重历史保留过短导致的历史 RSS 条目被重复识别并再次推送的问题

## [1.0.1] - 2026-04-06

### Added

- 为 `Sub` 模型新增 `platform_name` 字段，用于选择最优发送器策略
- 新增 `ChannelInfo` 与 `NotifierContext` DTO，用于封装通知元数据
- 新增全局 `set_bot_self_id_provider` 机制，用于动态解析 bot self_id

### Changed

- 重构 session_id 构造逻辑：使用 `event.unified_msg_origin` 替代自定义函数
- 重构发送器选择逻辑：改为使用 `platform_name` 字段，不再依赖 session_id 前缀匹配
- `AiocqhttpMessageSender` 现在使用 feed 标题作为合并转发节点昵称

### Fixed

- 修复监控循环中的 SQLAlchemy 嵌套会话事务错误
- 修复因 target_session 中平台标识错误导致的消息发送失败

### Removed

- 移除 `get_session_id` 工具函数（改用 `event.unified_msg_origin`）
- 移除 `get_sender_for_session` 函数（改用 `get_sender_for_platform_name`）
- 移除 `bot_self_id` 数据库字段（改为通过 provider 动态解析）

