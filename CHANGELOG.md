# Changelog

## [1.0.20] - 2026-04-20

### Changed

- 调整插件日志输出包装器（`utils/log_utils.py`）的调用栈处理逻辑，透传 `stacklevel`，避免包装层吞掉真实调用位置信息。
- 日志来源定位改为跟踪实际业务调用方，减少日志统一落在 `utils.log_utils` 的问题。

### Fixed

- 修复日志来源文件/行号显示偏移问题，日志现在能够正确指向触发日志的调用方，便于排查问题。

## [1.0.19] - 2026-04-19

### Added

- 新增 QQ 官方视频转码能力：
  - 在插件层发送链路中，QQ 官方视频发送前可自动转码为 H264/AAC MP4
  - 目标为优先保持“视频卡片”发送体验，而非直接降级为文本链接
- 新增配置项：
  - `qq_official_video_transcode`（默认 `true`）：控制 QQ 官方视频自动转码
  - `qq_official_auto_install_ffmpeg`（默认 `true`）：自动使用插件依赖提供的 FFmpeg 可执行文件
- 新增 `imageio-ffmpeg` 依赖，插件安装时即可自动携带可用 FFmpeg 运行时

### Changed

- QQ 官方发送器在视频发送前会按需补全本地媒体并执行转码预处理，再进入平台上传流程
- `/rss_conf` 与帮助文档已同步支持上述两个新配置项

### Fixed

- 针对 QQ 官方接口 `40034002`（富媒体文件格式不支持）场景，补充插件层格式兼容处理路径

## [1.0.18] - 2026-04-19

### Changed

- 重构 `entry_hashes` 存储结构，由扁平 `list[str]` 改为以 entry 为单位的二维数组 `list[list[str]]`：
  - 每条 entry 的全部指纹（身份哈希、内容哈希、上游 CRC、遗留 CRC）作为一个分组整体存储与淘汰
  - `hash_history_min` 等配置项的语义与实际行为对齐：`200` 即保留 200 条 entry，而非 200 个散列值
  - 历史窗口截断以 entry 为单位，不再出现一条 entry 的指纹被部分截断的情况
  - 大量新内容涌入时，旧 entry 按组整体淘汰，避免半截指纹残留导致去重失效
- `_merge_hash_history` 合并逻辑改为按 identity hash（`sid:`）去重，同一条 entry 更新内容后不会产生冗余副本

### Added

- 新增首次订阅时 `entry_hashes` 预填充：
  - `/sub` 创建新 feed 时，利用已抓取的 RSS 条目立即生成去重指纹并写入数据库
  - 避免首轮监控因 `entry_hashes` 为空而将全部历史条目误判为新内容推送
- 新增 `_migrate_flat_hashes` 运行时兼容方法：
  - 自动检测旧版扁平 `list[str]` 格式并按 `sid:` 边界分组迁移为新的 `list[list[str]]` 结构
  - 无需手动数据库迁移，升级后首轮监控自动完成格式转换

### Fixed

- 修复 `_merge_hash_history` 的 `entry_count` 传参错误：旧版传入的是 hash 总数而非 entry 数，导致历史窗口虚增约 4 倍
- 修复 `_calculate_update` 去重判定中 `entry_count` 语义与实际不符的问题

## [1.0.17] - 2026-04-19

### Changed

- 调整监控并发模型为“订阅级调度、feed 级更新串行化”：
  - 不同订阅仍按各自 `interval` / `next_check_time` 判断是否到期
  - 但同一个 RSS Feed 在任意时刻只允许一个协程进入更新流程，避免多个订阅同时处理同一 Feed

### Fixed

- 修复同一 Feed 被多个订阅几乎同时轮询时可能出现的重复推送问题：
  - 为 `Feed` 更新流程增加 feed 级互斥保护，串行化抓取、去重、推送与 `entry_hashes` 持久化
  - 避免多个协程同时读取同一份旧的 `feed.entry_hashes`，将同一条内容重复判定为“新条目”

## [1.0.16] - 2026-04-19

### Added

- 新增推送调试配置项 `debug_payload`：
  - 开启后可在推送末尾附带 `guid`、`id`、`link`、`published`、`updated` 等原始字段
  - 便于排查 RSS 源字段异常与去重行为

### Changed

- 调整 RSS 条目主身份判定优先级为 `guid > link > title > summary`
- 主身份哈希不再携带时间戳，避免仅时间字段抖动导致同一条内容被误判为新条目

### Fixed

- 修复部分 RSS 源在 `link` 显示一致时仍被重复推送的问题：
  - 统一监控阶段与推送阶段的链接解析语义，降低相对链接、绝对链接或不同表示形式导致的重复判定偏差
- 修复回滚去重策略后残留日志引用 `dedupe_strategy` 导致的 `F821 Undefined name` 问题
- 修复 `_conf_schema.json` 配置结构，使其更符合 AstrBot WebUI 所需的对象字段定义格式

## [1.0.15] - 2026-04-17

### Added

- 新增微信个人号（`weixin_oc`）平台专用发送器策略，适配“每条消息只能包含一个消息组件”的平台约束：
  - 图片、视频、音频、文件按单组件顺序发送
  - 文本内容单独发送，避免将多组件消息链直接交给平台
  - 媒体下载失败时，会在文本中附带原始链接作为兜底
  - 新增配置项 `sender_strategy_weixin_oc`，可通过 `/rss_conf sender_strategy_weixin_oc <true/false>` 开启或关闭该策略

### Changed

- 去重与监控链路优化：
  - 调整监控侧判重为“稳定身份优先 + 兼容指纹回退”，降低仅时间戳抖动导致的重复推送
  - 新增/完善监控轮次结构化统计日志，包含抓取条数、去重新增/跳过、扇出订阅数及失败队列处理计数
  - 首轮行为支持配置 `bootstrap_skip_history`（默认 `true`）：可选“仅建历史不推送”或“首轮补推历史”
- 配置与命令入口同步：
  - 新增配置项 `bootstrap_skip_history`，并接入配置加载/保存、`/rss_conf` 解析与展示
  - `/rsshelp` 与配置项说明补充 `failed_queue_max_retries` 与 `bootstrap_skip_history`
- 失败队列容量判定边界修正：
  - `FailedNotification.is_at_capacity` 从 `>` 调整为 `>=`，达到容量即判满

### Fixed

- 修复 QQ Official 在 Docker 场景下图片媒体路径被错误解析导致的 `FileNotFoundError`：
  - `file:///` 本地 URI 在发送前统一归一化为绝对本地路径，避免核心链路旧版切片逻辑（如 `i.file[8:]`）将路径误变为相对路径

- 修复失败队列观测盲区：
  - `Notifier` 增加失败入队、丢弃、处理成功、重试中、重试耗尽等统计计数，便于定位“漏推”来源

### Docs

- 文档同步更新：
  - `README.md` 新增 `bootstrap_skip_history` 说明
  - 明确“监控主循环无固定每周期条目上限”，实际受源更新量、失败队列容量、最大重试次数与平台限流影响

## [1.0.14] - 2026-04-14

### Added

- 新增微信个人号（`weixin_oc`）平台专用发送器策略，适配“每条消息只能包含一个消息组件”的平台约束：
  - 图片、视频、音频、文件按单组件顺序发送
  - 文本内容单独发送，避免将多组件消息链直接交给平台
  - 媒体下载失败时，会在文本中附带原始链接作为兜底
  - 新增配置项 `sender_strategy_weixin_oc`，可通过 `/rss_conf sender_strategy_weixin_oc <true/false>` 开启或关闭该策略

### Changed

- 去重与监控链路优化：
  - 调整监控侧判重为“稳定身份优先 + 兼容指纹回退”，降低仅时间戳抖动导致的重复推送
  - 新增/完善监控轮次结构化统计日志，包含抓取条数、去重新增/跳过、扇出订阅数及失败队列处理计数
  - 首轮行为支持配置 `bootstrap_skip_history`（默认 `true`）：可选“仅建历史不推送”或“首轮补推历史”
- 配置与命令入口同步：
  - 新增配置项 `bootstrap_skip_history`，并接入配置加载/保存、`/rss_conf` 解析与展示
  - `/rsshelp` 与配置项说明补充 `failed_queue_max_retries` 与 `bootstrap_skip_history`
- 失败队列容量判定边界修正：
  - `FailedNotification.is_at_capacity` 从 `>` 调整为 `>=`，达到容量即判满

### Fixed

- 修复 QQ Official 在 Docker 场景下图片媒体路径被错误解析导致的 `FileNotFoundError`：
  - `file:///` 本地 URI 在发送前统一归一化为绝对本地路径，避免核心链路旧版切片逻辑（如 `i.file[8:]`）将路径误变为相对路径

- 修复失败队列观测盲区：
  - `Notifier` 增加失败入队、丢弃、处理成功、重试中、重试耗尽等统计计数，便于定位“漏推”来源

### Docs

- 文档同步更新：
  - `README.md` 新增 `bootstrap_skip_history` 说明
  - 明确“监控主循环无固定每周期条目上限”，实际受源更新量、失败队列容量、最大重试次数与平台限流影响

## [1.0.14] - 2026-04-14

### Added

- 新增免费 RSS 源实例文档 [README.md](README.md)

## [1.0.13] - 2026-04-14

### Changed

- 优化数据库迁移逻辑：
  - 修复 `_migrate_user_id_to_text` 中的嵌套事务问题，避免 SQLAlchemy 事务状态冲突
  - 添加索引和触发器的备份恢复机制，表重建后自动恢复原有索引和触发器
  - 提取 `_get_column_type` 为模块级辅助函数，供多个迁移函数共享

### Fixed

- 修复 `selectinload` 类型注解警告，使用字符串形式避免 SQLAlchemy 2.0 类型检查问题

## [1.0.12] - 2026-04-13

### Added

- 新增 `qq_official` 平台专用发送器，解决多媒体被截断问题：
  - 单张图片：与文本一起发送
  - 多张图片：逐张单独发送，然后单独发送文本
  - 视频：先发送视频，再发送文本描述

## [1.0.11] - 2026-04-13

### Changed

- **破坏性变更**: 数据库 `user_id` 字段类型从 `INTEGER` 改为 `TEXT`，以适配多平台差异：
  - 微信个人号平台的 `user_id` 为字符串类型
  - QQ 和 Telegram 平台的 `user_id` 为整数类型
  - 所有平台的 `user_id` 现在统一以字符串形式存储
  - 插件启动时自动检测并迁移旧数据库（INTEGER → TEXT）

### Fixed

- 修复微信个人号平台因 `user_id` 类型不匹配导致的订阅/查询失败问题

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
