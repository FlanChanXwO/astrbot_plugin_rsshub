# Changelog

## [2.0.3] - 2026-06-01

### Added

- 新增 `http_config`，统一配置 RSS 拉取、媒体预下载与 FFmpeg m3u8/HLS 下载使用的代理和超时。
- 新增 `http_config.media_timeout`，用于单独配置媒体下载超时，上限提升到 1800 秒。
- Plugin Pages 推送历史新增单条「重试」操作，可人工重放旧记录并把本次结果写回原历史行；列表按最近活动时间排序，重试后该行会回到顶部。
- `rss_subscribe` AI 工具收口为单参数 `targets: string[]`，支持一次订阅多个完整 URL 或 RSSHub 路由路径。
- `rss_push_xml_entry` AI 工具新增安全排版参数，可临时指定 `style`、`send_mode`、媒体/标题/作者/via/tags 显示和正文长度。
- 为缺失中文命名别名的命令增加了命令别名。
- 新增数据库用户一致性自愈：订阅或推送历史引用到的 `user_id` 会在启动迁移阶段补齐到用户表。
- Plugin Pages 用户、Feed、订阅删除流程新增「同时清理推送历史」选项，默认保留历史审计数据。
- Plugin Pages 订阅列表新增按 Feed URL 精确筛选入口，推送历史跳转订阅不再依赖可能复用的 `sub_id`。
- 新增跨平台测试脚本 `tests/run_tests.sh`，方便 macOS/Linux 本地执行分类测试。

### Changed

- OneBot 默认优先使用插件预下载后的本地视频文件，避免 NapCat/OneBot 端自行拉取 m3u8 或远程视频导致发送失败。
- Telegram photo 大小阈值收口为内置常量，默认 10 MiB；超限图片会按文件发送。
- QQ Official 默认不再按媒体数量预先降级为文件；多媒体会优先按图片/视频组件发送，真实发送失败后再按内置策略降级为文件或原始链接。
- QQ Official Markdown 配置暂时保留为兼容入口，但主动推送临时统一纯文本，避免 Markdown 原文在 QQ 官方平台直接暴露。
- 旧 `basic_config.proxy`、`basic_config.timeout`、`media_config.download_media_timeout` 和 `m3u8_download_timeout` 会在启动配置自愈时迁移到 `http_config`。
- 表格图片渲染从 `infrastructure.media` 归位到 `infrastructure.rendering`，媒体包只保留下载、指纹和发送前媒体处理职责。

### Removed

- 媒体缓存 GC、媒体完整性阈值和平台降级策略收口为内置常量，不再作为用户配置项暴露。

### Fixed

- 修复无声视频转 GIF 后仍按视频组件上传的问题；转换后的 `.gif` 会统一按图片发送，并覆盖普通发送与原始顺序排版路径。
- 修复坏媒体文件可能进入成功缓存的问题；命中缓存和写入缓存前都会做基础完整性校验，坏缓存会被删除并触发重新下载。
- 修复 m3u8/HLS 合并输出校验不足的问题；FFmpeg 输出必须通过视频流与时长校验后才会写入成功缓存。
- 修复 QQ Official 单图+文本合发失败时可能静默丢失媒体的问题；失败会按内置策略优先文件降级，并在结果/文本中保留可见的原始媒体链接。
- 修复表格图片缓存并发写入、original layout 占位文本、generated media 缺失时暴露内部标识，以及关闭媒体时表格正文丢失的问题。

<details>

## [2.0.2] - 2026-05-23

### Changed

- 媒体发送统一先下载到本地成功缓存后再交给平台发送器；旧配置 `download_media_before_send=false` 不再影响运行时。
- 从 `_conf_schema.json` 移除 `basic_config.download_media_before_send`，插件启动时会清理实际配置文件中的遗留字段。
- 插件启动配置会按当前 `_conf_schema.json` 自动自愈：补齐缺失字段、移除未知字段、修正常见类型错误，并按下拉选项与滑块范围收敛非法值。

### Fixed

- 移除媒体下载失败缓存；下载失败不再写入内存或 `.fail` 文件，网络、代理或反代恢复后同一媒体会在下次推送重新尝试下载。
- 保留成功媒体缓存行为，避免重复下载已成功缓存的媒体。
- 修复启用代理后，FFmpeg m3u8/HLS 下载没有显式走代理的问题；裸 `host:port` 代理配置现在会统一按 `http://host:port` 处理。
- 修复 `/sub_import` 不带参数进入上传等待后，后续上传 TOML 文件未被监听处理的问题。
- 修复 Plugin Pages 推送历史保留 1 天 / 1 周 / 30 天清理按钮清理不充分的问题；清理判断改为按最后活动时间，并返回真实清理数量。
- 修复测试推送在真实发送失败时误报“未进入正式发送链路”的问题，现在会优先显示 sender 返回的失败原因。
- 修复 Telegram 本地图片超过 Bot API photo 大小限制时仍按图片发送的问题；超过 10 MiB 的图片会降级为文件发送。
- 修复 bsky 等源在关闭标题显示后，正文开头与标题相同导致 `#` 前正文被误删的问题。
- 修复 m3u8/HLS 先下载后发送时可能缓存 0 秒坏视频的问题，FFmpeg 输出会在入缓存前校验视频流与时长。

## [2.0.1] - 2026-05-23

### Fixed

- 修复 Plugin Pages 默认订阅设置保存时，前端 reactive payload 直接传入 AstrBot bridge 导致 `postMessage` 无法克隆并保存失败的问题。
- 修复媒体下载失败后在重试、重复推送或插件重启场景下短时间反复请求同一 URL、持续刷 WARN 日志的问题；新增短 TTL 磁盘失败缓存，近期失败的媒体会快速失败并保留原有发送降级语义。

## [2.0.0] - 2026-05-22

### Added

- 新增 `/rsshelp`、`/sub_status`、`/sub_stop`、`/rsshub_kb_init`、`/rsshub_kb_sync`、`/rsshub_kb_status`、`/rsshub_kb_task` 等命令。
- 新增 AstrBot Plugin Pages 管理面板，覆盖订阅、用户、Feed、推送历史、默认订阅设置、处理器、数据管理和 RSSHub Routes 知识库同步。
- 新增 schema-driven 内容处理链，内置 `ai_filter` 与 `ai_transform`；`ai_transform` 支持 `plaintext` 与 `xml` scope，XML 改写会经过校验和重新解析。
- 新增推送排版策略：`style=0` 自动，`style=1` RSSRT，`style=2` 原始顺序；原始顺序会尽量按 RSS/HTML 解析树保留图文相邻关系。
- 新增 RSSHub Routes 知识库同步命令与 Web API：`/rsshub_kb_init`、`/rsshub_kb_sync`、`/rsshub_kb_status`、`/rsshub_kb_task`。
- 新增 AI agent 工具 `rss_list_push_history` 与 `rss_push_xml_entry`，支持查询推送历史和提交 XML/HTML 即时推送。
- 新增推送历史详情、批量操作、自动清理配置和订阅联动筛选；新增缓存与导出文件的数据管理视图。

### Changed

- 配置体系重构：启动级配置保留在 `_conf_schema.json`，订阅默认值和处理链配置迁移到 Plugin Pages；类型化运行时配置收口到 `src/infrastructure/config/`。
- 数据模型收口：用户/订阅配置统一使用 `-100` 表示继承，移除旧 `use_sub_config` / `use_user_config` / 翻译列；迁移脚本压缩为当前 v2 基线。
- 发送链路重构：格式化器只负责解析后的文本和媒体，平台差异放在 sender adapter；OneBot、QQ Official、Weixin OC、Telegram 使用各自平台策略。
- Plugin Pages 不再提供新增订阅或订阅 TOML 导入/导出入口；这些用户归属明确的操作继续通过聊天命令或 AI agent 工具完成。
- 文档体系重建为 `docs/README.md`、`docs/project/`、`docs/dev/`、`docs/usage/`，README 只保留入口和用户向说明。

### Fixed

- 修复部分 RSS 源只推送图片不推送正文的问题，补齐 `content:encoded`、HTML 文本提取、图文 layout fragment 和平台发送顺序处理。
- 修复旧库迁移到 v2 后 `rsshub_sub.handlers_mode` 缺失导致 `/sub_list` 查询失败的问题。
- 修复失败重试和推送历史审计链路：推送历史保存媒体 URL、原始 XML、handler trace，并限制失败原因长度。
- 修复 Routes KB raw URL 拼接，支持代理前缀形式的 GitHub Raw 镜像。

### Removed

- 移除传统翻译管道、翻译缓存、旧内容增强管道和旧 route-search LLM tools。
- 移除冗余内置处理器 `xml_parse`；HTML/XML 清洗归入基础解析与格式化链。
- 移除旧版配置管理 shim、碎片开发期迁移脚本和 Plugin Pages 中不应承担用户归属的导入/导出入口。

## [1.1.3] - 2026-04-28

### Fixed

- **优化 FFmpeg 查找策略**：`ensure_ffmpeg_ready` 方法现在优先使用系统 FFmpeg，以确保编解码器和协议的完整支持

## [1.1.2] - 2026-04-26

### Fixed

- **移除推送时图片上限**：
  - 解决 RSS 源包含大量图片时只推送 9-14 张的问题

## [1.1.1] - 2026-04-26

### Fixed

- 修复首次订阅时的哈希存储问题

## [1.1.0] - 2026-04-23

### Breaking Changes

- **命令更名**:
  - `/sub_set_default` → `/sub_set_user` (设置用户配置)
  - `/sub_session_default_set` → `/sub_set_session` (设置会话默认)
  - `/sub_session_default_get` → `/sub_get_session` (获取会话默认)
  - `/sub_bind` → **已删除** (功能已整合)

- **`/sub_test` 命令重构**（破坏性变更）：
  - 参数格式完全改变：从粒度模式 (`latest`/`all`/`<数量>`) 改为条目编号范围
  - 新格式：`/sub_test <目标> [起始编号] [结束编号]`
  - 支持通过 URL 直接测试（无需先订阅）
  - 条目编号从 1 开始（1 = 最新发布的条目）
  - 示例：`/sub_test 5 1 3`（推送订阅ID=5的条目1-3）
  - URL测试示例：`/sub_test https://example.com/rss.xml 1 5`
  - URL测试时使用全局配置

- **配置管理架构重构**：
  - 引入 ConfigProxy 单例模式，全局配置通过 `cfg` 对象统一管理
  - 所有模块通过 `from ..config import cfg` 访问配置，无需层层传递
  - 支持配置热重载 (`cfg.reload()`) 和重载钩子机制 (`register_reload_hook`)
  - 细粒度写锁保护，单配置项修改 (`cfg.set_value()`) 线程安全

- **命令调整**：
  - 移除 `/rss_conf` 命令，全局配置请前往 AstrBot 管理面板 设置

### Added

- **三层配置继承架构**:
  - Sub 表新增 `use_sub_config` 字段：控制是否使用订阅自身配置
  - User 表新增 `use_user_config` 字段：控制是否使用用户自身配置
  - 默认行为：订阅 → 继承用户 → 继承全局（开箱即用）
  - 新增命令：
    - `/sub_set_user` / `/sub_get_user` - 用户配置管理
    - `/sub_set_session` / `/sub_get_session` - 会话默认管理
  - 布尔值支持多种格式：true/false, yes/no, y/n, 1/0, on/off, enable/disable

- **批量操作命令**:
  - `/sub <url1> [url2...]` - 批量订阅多个 RSS 源
  - `/unsub <id1> [id2...]` - 批量取消订阅（支持 ID 或 URL）
  - `/activate_subs` (别名 `/enable_subs`) - 启用当前会话所有订阅
  - `/deactivate_subs` (别名 `/disable_subs`) - 禁用当前会话所有订阅

- **订阅状态管理**:
  - `/sub state <id> on/off` - 快速启停单个订阅推送
  - 支持多种布尔值格式

- **RSS 内容自动翻译功能** (Translation Support):
  - 新增 Google 翻译支持（免费，开箱即用）
  - 新增百度翻译支持（需申请 AppID 和密钥）
  - 支持目标语言：`zh-CN`(简体中文)、`zh-TW`(繁体中文)、`en`(英文)、`ja`(日文)
  - 支持标题和正文分别控制是否翻译
  - 支持显示原文与译文（格式：`原文 +
--【译文】--
 + 译文`）
  - 智能语言检测，避免无意义翻译（可强制翻译跳过检测）
  - 翻译结果缓存，减少重复 API 调用，缓存跟随条目淘汰策略
  - 按订阅级翻译控制，可通过 `/sub_set` 为特定订阅单独配置

- **翻译提供商扩展架构**:
  - 新增 `BaseTranslator` 抽象基类，便于后续添加更多翻译提供商
  - 提供 `register_provider()` 函数支持动态注册新提供商
  - 完整的提供商开发文档 (`translation/providers/README.md`)

- **数据库迁移管理优化**:
  - 将数据库迁移逻辑抽取到独立的 `db/migrations.py` 文件
  - 新增 `TranslationCache` 表用于存储翻译缓存
  - 新增 `translate` 和 `translate_target_lang` 字段到 User 和 Sub 表
  - 新增 `use_sub_config` 和 `use_user_config` 字段
  - v1.1.0 迁移：将 INHERIT_VALUE (-100) 替换为实际默认值
  - 完善数据库迁移逻辑，支持旧版本平滑升级

### Added

- **三层配置继承架构**：订阅级 → 用户级 → 全局级，开箱即用
  - 新增 `/sub_set_user` / `/sub_get_user` - 用户配置管理
  - 新增 `/sub_set_session` / `/sub_get_session` - 会话默认管理
- **批量操作命令**：支持批量订阅、批量取消订阅、启用/禁用全部订阅
- **RSS 内容自动翻译**：支持 Google（免费）和百度翻译
- **订阅状态管理**：`/sub_state <ID> on/off` 快速启停单个订阅推送

### Break Changed

- **命令更名**：
  - `/sub_set_default` → `/sub_set_user`
  - `/sub_session_default_set` → `/sub_set_session`
  - `/sub_session_default_get` → `/sub_get_session`
  - `/sub_bind` → **已删除**
- **`/sub_test` 命令重构**：参数从粒度模式改为条目编号范围，支持 URL 直接测试
- **移除 `/rss_conf` 命令**：全局配置请前往 AstrBot 管理面板设置
- **移除平台共享数据功能**：订阅数据不再支持跨 BOT 平台共享

### Changed

- **数据库表结构简化**：用 `rsshub_sub.next_check_time` 替代独立的 monitor_schedule 表
- **监控调度优化**：按 (feed_id, interval) 分组以减少 HTTP 请求

### Fixed

- **修复 RSS 监控可能漏推的问题**：
  - `history_entry_limit` 默认值从 `10` 改为 `0`（不限制）
  - 修复时间解析失败导致的排序异常
  - 修复数据库与推送非原子性问题（先推送成功后才更新数据库）
- **修复批量操作 SQLAlchemy Greenlet 错误**
- **修复媒体缓存 GC 与缓存写入并发竞争**
- **修复 Telegram 媒体发送 `Wrong http url specified` 问题**
- **修复 QQ Official Docker 场景下图片媒体路径被错误解析**
- **修复同一 RSS 源在多平台/多会话并发订阅时的推送抢占**
- **修复 `sub_list` 显示问题**：现在返回所有订阅（包括禁用状态）
- **修复 `sub_test` URL 模式推送目标缺失**
- **修复 aiocqhttp 合并转发失败时退化为直发文本消息的问题**

---


### Refactored

- **工具模块重构为 OOP 风格**：
  - `utils/ffmpeg_helper.py` → `FFmpegTool` 类（静态方法）
    - 删除无效的 `imageio_ffmpeg` try-except 导入
    - 修复 `process` 变量未赋值警告（提前初始化为 `None`）
    - 细化异常捕获：`except Exception` → `except (OSError, asyncio.TimeoutError, ValueError)`
    - 删除 `process.kill()/wait()` 的冗余异常捕获
    - 函数名变更：`transcode_video_to_mp4_for_qq()` → `transcode_to_mp4()`
  - `utils/aio_helper.py` → `utils/concurrent.py`
    - 删除旧文件，功能合并到 `concurrent.py`
    - 提供 `AsyncTool` 静态方法类和装饰器
  - `utils/locks.py` → 新增 `locked()` 装饰器（基于 SpEL 表达式）
    - 支持 `@locked("#feed.id")`、`@locked("#user_id")` 等语法
    - 保留向后兼容的便捷函数

### Fixed

- **修复批量操作 SQLAlchemy Greenlet 错误**：
  - `batch_activate_subs` / `batch_deactivate_subs` 使用 `selectinload(Sub.feed)` 预加载 feed
  - 避免访问 `sub.feed.title` 时触发懒加载导致的 greenlet 错误
- **TranslationManager 单例化**：
  - 避免每次通知都创建新的 TranslationManager 和 aiohttp.ClientSession
  - 减少资源开销，提高性能
- **修复 `sub_list` 显示问题**：
  - `Sub.get_by_user()` 现在返回所有订阅（包括禁用状态）
  - 添加会话状态统计：显示总订阅数、启用数、禁用数
  - 每个订阅前添加状态图标（✓ 启用 / ✗ 禁用）
- **修复 `sub_test` URL 模式推送目标缺失**：
  - 创建临时 Sub 对象时添加 `target_session` 字段
- **修复命令组语法**：
  - `@filter.command(cmd_sub, sub_command="state")` → `@cmd_sub.command("state")`

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
  - 目标为优先保持"视频卡片"发送体验，而非直接降级为文本链接
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

- 调整监控并发模型为"订阅级调度、feed 级更新串行化"：
  - 不同订阅仍按各自 `interval` / `next_check_time` 判断是否到期
  - 但同一个 RSS Feed 在任意时刻只允许一个协程进入更新流程，避免多个订阅同时处理同一 Feed

### Fixed

- 修复同一 Feed 被多个订阅几乎同时轮询时可能出现的重复推送问题：
  - 为 `Feed` 更新流程增加 feed 级互斥保护，串行化抓取、去重、推送与 `entry_hashes` 持久化
  - 避免多个协程同时读取同一份旧的 `feed.entry_hashes`，将同一条内容重复判定为"新条目"

## [1.0.16] - 2026-04-19

### Added

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

- 新增微信个人号（`weixin_oc`）平台专用发送器策略，适配"每条消息只能包含一个消息组件"的平台约束：
  - 图片、视频、音频、文件按单组件顺序发送
  - 文本内容单独发送，避免将多组件消息链直接交给平台
  - 媒体下载失败时，会在文本中附带原始链接作为兜底
  - 新增配置项 `sender_strategy_weixin_oc`，可通过 `/rss_conf sender_strategy_weixin_oc <true/false>` 开启或关闭该策略

### Changed

- 去重与监控链路优化：
  - 调整监控侧判重为"稳定身份优先 + 兼容指纹回退"，降低仅时间戳抖动导致的重复推送
  - 新增/完善监控轮次结构化统计日志，包含抓取条数、去重新增/跳过、扇出订阅数及失败队列处理计数
  - 首轮行为支持配置 `bootstrap_skip_history`（默认 `true`）：可选"仅建历史不推送"或"首轮补推历史"
- 配置与命令入口同步：
  - 新增配置项 `bootstrap_skip_history`，并接入配置加载/保存、`/rss_conf` 解析与展示
  - `/rsshelp` 与配置项说明补充 `failed_queue_max_retries` 与 `bootstrap_skip_history`
- 失败队列容量判定边界修正：
  - `FailedNotification.is_at_capacity` 从 `>` 调整为 `>=`，达到容量即判满

### Fixed

- 修复 QQ Official 在 Docker 场景下图片媒体路径被错误解析导致的 `FileNotFoundError`：
  - `file:///` 本地 URI 在发送前统一归一化为绝对本地路径，避免核心链路旧版切片逻辑（如 `i.file[8:]`）将路径误变为相对路径

- 修复失败队列观测盲区：
  - `Notifier` 增加失败入队、丢弃、处理成功、重试中、重试耗尽等统计计数，便于定位"漏推"来源

### Docs

- 文档同步更新：
  - `README.md` 新增 `bootstrap_skip_history` 说明
  - 明确"监控主循环无固定每周期条目上限"，实际受源更新量、失败队列容量、最大重试次数与平台限流影响

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
  - 当时新增的 `sender_strategies.telegram` / `sender_strategies.aiocqhttp` 子项已在后续版本迁移为 `enabled_platforms` + `platform_strategies`
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
- 优化缓存 GC 锁粒度：采用"扫描无锁 + 删除加锁"两阶段流程，降低高并发下载场景下的锁竞争
- 清理 `/sub_list` 历史分片残留逻辑与无用常量，避免后续维护歧义

## [1.0.5] - 2026-04-07

### Changed

- 调整 `/sub_list all` 为管理员全局视图：展示数据库内所有平台/会话订阅
- 为管理员全局列表新增分页能力：支持 `/sub_list all [page] [page_size]`，避免一次性加载/输出全量数据

### Fixed

- 修复同一 RSS 源在多平台/多会话并发订阅时的推送抢占：单次更新统一扇出到该源全部活跃订阅，避免条目被不同会话分走
- 修复开启"先下载图片再发送"后，aiocqhttp 合并转发路径偶发 `ENOENT`（媒体缓存文件提前删除）的问题
- 修复媒体缓存 GC 与缓存写入并发竞争导致的 `ENOENT`：为缓存 GC/读写引入 I/O 互斥并添加下载后双重检查
- 修复 `rsshelp` 文案中的乱码问题

## [1.0.4] - 2026-04-07

### Changed

- 调整 `AiocqhttpMessageSender` 回退策略为"仅合并转发"：合并转发失败后不再尝试非合并消息链
- 新增 aiocqhttp 合并失败兜底链路：改为发送"纯文本合并节点"，保持推送形态一致

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
- `/unsub_all` 行为明确为"默认当前会话，`global` 全局删除（管理员）"，并移除历史 `yes` 参数语义

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

</details>
