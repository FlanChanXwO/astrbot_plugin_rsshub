# 兼容性说明

## RSS 解析

- RSS 解析优先读取 `content` 结构化正文，并兼容 `content:encoded` / `content_encoded` 字段。
- HTML `<video>`、`<audio>` 会作为结构化媒体传入发送器，正文中不会残留 `[视频]` / `[音频]` 占位。
- RSSHub 常见的 `?url=<encoded media>` 包装链接会参与媒体类型推断。
- 关闭标题显示时，正文不会因为与标题开头重复而被剔除。

## 媒体发送

- 发送前会先下载媒体到本地成功缓存，再根据本地文件头和 `filetype` 探测结果修正图片、视频、音频类型。
- 下载失败不会写入失败缓存，下一次推送会重新尝试。
- m3u8/HLS 会通过 FFmpeg 合并为 MP4，并用 ffprobe 校验视频流与时长。
- 本地图片超过平台限制时会按平台能力降级为文件、链接或文本 fallback。
- HTML 表格可按 `media.table_to_image` 渲染为图片，关闭后使用文本表格 fallback。

## 平台差异

- OneBot / NapCat 经典排版按合并转发发送；失败后会回退为纯文本 nodes。
- OneBot 原始顺序排版会按 RSS/HTML 解析出的布局片段逐条发送，适合多图长文。
- Telegram 多媒体自动策略可使用 Telegraph 分流；本地图片超过 Bot API photo 限制时会降级为文件发送。
- QQ Official 当前主动推送临时统一为纯文本 Markdown 行为，待 AstrBot core 主动推送的消息级 Markdown 行为稳定后再恢复三态策略。

## 升级兼容

- `minimal_interval` 是保存期硬限制，所有写入订阅、用户默认值、会话默认值的入口都不能保存更小值。
- `failed_queue_capacity=0` 只禁用自动失败重试队列，不关闭失败历史记录。
- `failed_queue_max_retries` 只控制自动重试次数；超过上限后仍保留失败历史。
- `deduplicate_multi_bot` 只在同一 `target_session` 内比较最终 payload 是否等价；命中后写入 `status=skipped` 审计记录。
- 插件启动时会补齐旧库中被订阅或推送历史引用、但缺失于 `rsshub_user` 的用户记录，避免孤儿订阅或孤儿历史。
