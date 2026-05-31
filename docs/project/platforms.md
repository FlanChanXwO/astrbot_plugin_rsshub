# 平台发送与媒体兼容规则

本文记录 sender、平台适配、媒体下载与格式化相关稳定语义。修改 `src/infrastructure/messaging/`、`src/infrastructure/media/`、`src/infrastructure/pipeline/` 时优先参考本文。

> [!NOTE]
> 插件目标仍然是面向 AstrBot 全平台；但当前明确做过专门适配和回归覆盖的平台 sender 是 OneBot / aiocqhttp、QQ Official、Telegram、Weixin OC。其他平台会落到默认发送者，可能可用，但不属于当前明确测试覆盖点。

## 当前支持与测试覆盖

| 平台 / sender | 当前状态 | 明确覆盖点 | 备注 |
| --- | --- | --- | --- |
| OneBot / aiocqhttp | 专门 sender，明确测试覆盖 | 合并转发、原始顺序、媒体预下载、NapCat 流式上传、失败 fallback | NapCat 支持流式上传大文件，默认 fallback 模式（失败后重试）。 |
| QQ Official | 专门 sender，明确测试覆盖 | 单图文本合链、多媒体拆发、Markdown 开关边界、媒体失败 partial 语义 | Markdown 必须走 AstrBot `MessageChain.use_markdown_`，不得绕过 core 手写 botpy payload。 |
| Telegram | 专门 sender，明确测试覆盖 | Telegraph 多图路由、大图片转文件、MarkdownV2 文本边界 | 不假设插件能控制媒体 caption Markdown。 |
| Weixin OC | 专门 sender，明确测试覆盖 | 顺序发送、original style 顺序调整、不做图文合一 | 平台能力不适合强行合链。 |
| 其他 AstrBot 平台 | 默认 sender，未列入当前专门回归覆盖 | 基础 `Plain` / 媒体组件发送 | 默认发送者不做强平台特化，因此可能可用；新增平台专属行为前需要补对应测试。 |

## 通用推送契约

| 契约 | 当前语义 | 备注 |
| --- | --- | --- |
| 推送尾部 | 保持 `via <link> | <feed> (author: ...)` 兼容格式 | 具体文本构造见 [`formatting.md`](./formatting.md)。 |
| 成功媒体链接 | 成功推送不追加原始媒体链接 | 避免正常内容被大量 URL 污染。 |
| 失败媒体链接 | 发送失败降级文本或失败历史中追加失败媒体原始链接 | 用于人工排障和后续重试。 |
| `style` / `send_mode` | 排版语义见 [`formatting.md`](./formatting.md)；分发语义见 [`dispatch.md`](./dispatch.md) | 本章不重复维护枚举表。 |

## 平台行为矩阵

| 平台 / sender | 文本与媒体顺序 | 媒体策略 | Markdown / Telegraph | 关键风险 |
| --- | --- | --- | --- | --- |
| OneBot / aiocqhttp | auto/classic 使用合并转发；original 按 layout fragments 发送 | 媒体预下载后使用本地文件；支持 NapCat 流式上传（disabled/fallback/always）；合并转发失败后回退纯文本 Nodes | 不使用 Telegraph；Markdown 不作为承诺面 | 合并转发失败、媒体发送失败、媒体顺序回退。 |
| QQ Official | 单图 + 文本合成一条 `Image + Plain`；视频和多媒体仍拆发 | 图片/视频先按平台媒体组件发送，失败后按内置策略降级 | `qq_official_strategy.markdown_mode=auto|force|plain` 语义保留；当前主动推送链路暂时显式关闭 Markdown | Markdown 原文暴露、媒体 + markdown payload 畸形、partial send 难排障。 |
| Telegram | 文本和媒体按 Telegram sender 策略发送 | 本地图片超过内置 photo 阈值时按文件发送 | Telegraph 是 Telegram sender 级自动路由，不是 `send_mode`；Plain 文本可走 AstrBot MarkdownV2 | Bot API photo 大小拒绝、caption Markdown 不一致。 |
| Weixin OC | 始终逐条发送；original 只影响顺序 | 不尝试图文合一 | 无 Telegraph / Markdown 承诺 | 强行图文合链会吞文本或失败。 |
| 默认 sender | 尽量使用平台通用 MessageChain 组件 | 不做平台专属降级 | 依赖 AstrBot 平台默认能力 | 未明确覆盖的平台行为可能和专门 sender 不一致。 |

## 媒体上限参考

> [!IMPORTANT]
> 下表区分“公开文档明确限制”和“插件暂定策略”。未公开的限制不要写成平台事实；QQ Official 这类网关行为需要继续用真实机器人账号实测。
> 采集日期：2026-05-27。这些平台标准来自当天开始的公开资料探索和项目实测经验，平台能力、实现细节和风控策略后续都可能变动。

| 平台 / 入口 | 图片 | GIF / 动图 | 视频 | 文件 | 插件当前口径 | 依据与备注 |
| --- | ---: | ---: | ---: | ---: | --- | --- |
| Telegram Bot API | `sendPhoto` 上传最大 10 MiB；HTTP URL photo 约 5 MiB | `sendAnimation` 最大 50 MiB | `sendVideo` 最大 50 MiB | `sendDocument` 最大 50 MiB | GIF 不走 photo，优先 animation；大静态图超 10 MiB 后按文件发送。 | Telegram 官方 Bot API 明确区分 photo、animation、video、document；Local Bot API Server 是例外，不作为默认阈值。 |
| QQ 客户端 / OneBot 逆向实现参考 | NapCat 图片/GIF 未查到公开硬阈值；普通客户端大图也可能按文件链路发送 | NapCat GIF 未查到公开硬阈值；QQ 自定义表情和普通图片发送限制不是同一条链路 | NapCat 文档写视频 100 MiB，超过建议走群文件 | 离线文件单文件 4 GiB；非会员离线流量 2 GiB/天；在线直传、群文件和 NTQQ 实现会受客户端、账号、群空间和风控影响 | OneBot 可以把 QQ 用户文件能力作为 fallback 参考：媒体消息发不出时优先改走文件链路，而不是直接判失败。 | OneBot 是 QQ 协议逆向/适配层，实际能力接近 QQ 客户端链路，但每个实现接入的上传 API 不同。本文默认以 NapCat 表现评估 OneBot 风险；go-cqhttp 的图片 30 MiB、GIF 300 帧只保留为旧实现资料。 |
| QQ Official | 官方未公开稳定上限；插件暂定单图 20 MiB | 官方未公开稳定上限；插件暂定 GIF 10 MiB | 官方未公开稳定上限；插件暂定视频 100 MiB | `file_type=4` 历史上有“不开放”口径，当前能力需实测 | 图片按 20 MiB 软上限评估；GIF 按 10 MiB 软上限评估；视频按 100 MiB 软上限评估；遇到 413/业务码保留原始错误并降级。 | QQ Bot OpenAPI 文档未给出图片/GIF/视频统一大小上限；`413 Request Entity Too Large` 更像上传网关限制。 |
| Weixin OC / 微信系 | 企业微信临时素材 image 常见 10 MiB；普通会话大图可能转文件 | 普通企业微信会话 GIF 超 5 MiB 常转文件；API 图片素材通常不承诺 GIF | 企业微信临时素材 video 10 MiB | 企业微信临时素材 file 20 MiB | Weixin OC 保持逐条发送，不尝试复杂图文合链；超限由平台错误和降级文本暴露。 | 微信入口差异很大：企业微信应用消息、临时素材、普通会话、公众号素材不是同一套限制。 |

这些数值统一按“软阈值”管理，只用于发送前分流、日志解释和降级判断，不应让正常可发送媒体被静默丢弃。软阈值不能被当作平台硬限制，也不能在数据层截断、丢弃或提前判定推送失败；真实发送失败仍应暴露平台错误，并进入可观测的降级链路。新增硬拒绝前必须有平台文档、稳定实测或用户配置作为依据。

软阈值集中由 `src/shared/constants.py` 归口，发送候选链路由 `MediaSendPlanner` 统一消费，不要散落在具体 sender 或文档表格里复制多份。当前固定口径包括：Telegram photo 默认 10 MiB 后改按文件发送、OneBot 支持 NapCat 流式上传（默认 fallback 模式）、QQ Official 默认不按媒体数量预先降级。QQ Official 表格里的 20 MiB / 10 MiB / 100 MiB 是 2026-05-27 的调查与实测参考，不是平台硬门槛。

## 媒体下载与缓存

| 规则 | 当前行为 | 原因 |
| --- | --- | --- |
| 发送前预下载 | 所有媒体发送前先下载到本地 | 避免平台直接拉远程资源失败、吞内容或格式不兼容。 |
| 成功缓存 | 只缓存成功下载并通过校验的媒体 | 缓存应代表可复用资产。 |
| 失败缓存 | 不写入内存失败缓存，也不写入磁盘 `.fail` | 网络、代理、Nginx 恢复后应允许下一次重新尝试。 |
| 后缀 | 成功缓存使用真实媒体类型和真实后缀 | 不把未知内容随意落成 `.bin`。 |
| 类型检测 | 发送前检测真实本地媒体类型，不信任 URL 扩展名 | URL 后缀、query 参数和代理包装都可能误导 sender。 |
| 图片 / 视频校验 | 缓存前和复用前都校验本地图片、视频 | 坏缓存不能进入发送链。 |
| m3u8 / HLS | 使用 FFmpeg 下载合并，并用 ffprobe 校验输出 | 拒绝零时长、无视频流或损坏输出。 |
| 失败语义 | 媒体失败不阻断 RSS 推送 | 失败媒体原始链接会作为降级信息保留。 |
| 本地生成媒体 | `<table>` 图片使用 `rsshub-generated://table/<hash>` 标识并直接映射 cache PNG | 它不是远程 URL，不经过 HTTP 下载，也不会在失败链接里暴露本地 cache 标识。 |
| 媒体反代 | `media.image_relay_base_url` / `media.media_relay_base_url` 默认关闭，开启后先尝试反代再回源 | 图片优先走图片反代；非图片或未配置图片反代时走通用媒体反代。缓存 key 和失败展示链接保持原始 URL。 |
| 下载并发 | `media.media_download_concurrency=1` 保持串行，大于 1 时同一条推送内并发预下载远程媒体 | 返回顺序保持输入顺序；重复 URL 仍只下载一次，重复项保留原有占位语义。 |

```text
远程媒体 URL
  -> 预下载
  -> 探测真实类型 / 后缀
  -> 图片或视频完整性校验
  -> 写入成功缓存与 variants
  -> MediaSendPlanner 选择候选
  -> 平台 sender 构造 MessageChain
```

本地生成媒体的入口不同：`HTMLParser` 生成 `GeneratedImageContent` 后，sender 会通过 `infrastructure.rendering` 的表格图片解析器把 `rsshub-generated://table/<hash>` 映射回 `cache/table_images/table_<hash>.png`，直接构造 `PreparedMedia`。如果 cache 文件缺失，会按媒体失败处理但不会把内部标识追加给用户，也不会在 original layout 中把内部标识当作图片文件发送；layout 会携带不可见的表格纯文本 fallback，供 cache 缺失或平台图片发送失败时补回正文。`media.table_to_image=false` 时表格解析阶段直接使用纯文本表格；渲染失败时也会回退为纯文本表格。

无声视频转 GIF 时会保留原始视频 variant。若 GIF 超出当前内置的跨平台压缩目标，插件会按固定 FFmpeg 档位尝试压缩 GIF；发送时再按目标平台软阈值选择原 GIF、压缩 GIF、原视频、文件或原始链接。

## 代理与超时

| 配置 | 作用范围 | 备注 |
| --- | --- | --- |
| `http_config.proxy` | RSS 拉取、普通媒体预下载和 FFmpeg 下载 | 这是全局 HTTP/SOCKS 代理来源，不影响 Telegraph API。 |
| `media.telegraph_proxy` | Telegram Telegraph API | 留空表示直连，不继承 `http_config.proxy`。 |
| 裸 `host:port` 代理 | 标准化为 `http://host:port` | 避免不同 HTTP 客户端对无 scheme 值表现不一致。 |
| SOCKS 代理 | `socks4://` / `socks5://` / `socks5h://` | Telegraph API 通过 `aiohttp-socks` 连接；SOCKS 代理必须带明确 scheme。 |
| `http_config.media_timeout` | 媒体预下载和 FFmpeg 下载超时 | 上限和默认值属于配置模型 / schema 约束。 |

## 常量放置

共享常量统一维护在 `src/shared/constants.py`。本章只记录平台发送语义，不重复维护常量分类清单。

更多 sender 结构见 [`sender.md`](./sender.md)。
