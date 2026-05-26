# 平台发送与媒体兼容规则

本文记录 sender、平台适配、媒体下载与格式化相关稳定语义。修改 `src/infrastructure/messaging/`、`src/infrastructure/media/`、`src/infrastructure/pipeline/` 时优先参考本文。

> [!NOTE]
> 插件目标仍然是面向 AstrBot 全平台；但当前明确做过专门适配和回归覆盖的平台 sender 是 OneBot / aiocqhttp、QQ Official、Telegram、Weixin OC。其他平台会落到默认发送者，可能可用，但不属于当前明确测试覆盖点。

## 当前支持与测试覆盖

| 平台 / sender | 当前状态 | 明确覆盖点 | 备注 |
| --- | --- | --- | --- |
| OneBot / aiocqhttp | 专门 sender，明确测试覆盖 | 合并转发、原始顺序、媒体预下载、本地视频优先、失败 fallback | NapCat/OneBot 远程拉取视频不稳定，因此成功预下载后默认优先本地视频。 |
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
| `style` / `send_mode` | 领域值统一维护在 [`domain-model.md`](./domain-model.md) | 本章不重复维护枚举表。 |

## 平台行为矩阵

| 平台 / sender | 文本与媒体顺序 | 媒体策略 | Markdown / Telegraph | 关键风险 |
| --- | --- | --- | --- | --- |
| OneBot / aiocqhttp | auto/classic 使用合并转发；original 按 layout fragments 发送 | 成功预下载后默认优先本地视频；合并转发失败后回退纯文本 Nodes | 不使用 Telegraph；Markdown 不作为承诺面 | 合并转发失败、远程视频拉取失败、媒体顺序回退。 |
| QQ Official | 单图 + 文本合成一条 `Image + Plain`；视频和多媒体仍拆发 | 图片/视频先按平台媒体组件发送，失败后按内置策略降级 | `qq_official_strategy.markdown_mode=auto|force|plain` 语义保留；当前主动推送链路暂时显式关闭 Markdown | Markdown 原文暴露、媒体 + markdown payload 畸形、partial send 难排障。 |
| Telegram | 文本和媒体按 Telegram sender 策略发送 | 本地图片超过内置 photo 阈值时按文件发送 | Telegraph 是 Telegram sender 级自动路由，不是 `send_mode`；Plain 文本可走 AstrBot MarkdownV2 | Bot API photo 大小拒绝、caption Markdown 不一致。 |
| Weixin OC | 始终逐条发送；original 只影响顺序 | 不尝试图文合一 | 无 Telegraph / Markdown 承诺 | 强行图文合链会吞文本或失败。 |
| 默认 sender | 尽量使用平台通用 MessageChain 组件 | 不做平台专属降级 | 依赖 AstrBot 平台默认能力 | 未明确覆盖的平台行为可能和专门 sender 不一致。 |

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

```text
远程媒体 URL
  -> 预下载
  -> 探测真实类型 / 后缀
  -> 图片或视频完整性校验
  -> 写入成功缓存
  -> 平台 sender 构造 MessageChain
```

## 代理与超时

| 配置 | 作用范围 | 备注 |
| --- | --- | --- |
| `http_config.proxy` | 媒体预下载和 FFmpeg 下载 | 这是全局 HTTP 代理来源，不存在 content 级代理配置。 |
| 裸 `host:port` 代理 | 标准化为 `http://host:port` | 避免不同 HTTP 客户端对无 scheme 值表现不一致。 |
| `http_config.media_timeout` | 媒体预下载和 FFmpeg 下载超时 | 上限和默认值属于配置模型 / schema 约束。 |

## 常量放置

常量归属统一维护在 [`domain-model.md`](./domain-model.md#常量归属)。本章只记录平台发送语义，不重复维护常量分类清单。

更多 sender 结构见 [`sender.md`](./sender.md)。
