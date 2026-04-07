# Changelog

## [1.0.5] - 2026-04-07

### Changed

- 调整 `/sub_list all` 为管理员全局视图：展示数据库内所有平台/会话订阅
- 为管理员全局列表新增分页能力：支持 `/sub_list all [page] [page_size]`，避免一次性加载/输出全量数据
- `sub_list` 输出改为纯文本分片发送，并根据 `platform_settings.forward_threshold` 动态收敛分片长度，降低被平台转换为合并消息的概率

### Fixed

- 修复同一 RSS 源在多平台/多会话并发订阅时的推送抢占：单次更新统一扇出到该源全部活跃订阅，避免条目被不同会话分走
- 修复开启“先下载图片再发送”后，aiocqhttp 合并转发路径偶发 `ENOENT`（媒体缓存文件提前删除）的问题
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
