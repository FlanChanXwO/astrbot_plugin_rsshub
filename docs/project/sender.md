# 发送、适配器与媒体指纹

## 负责什么

这一章覆盖三个紧密相关的部分：

- `NotificationServiceImpl`
- sender adapter / provider
- media fingerprint

## 为什么要单独写这一层

“发消息”看起来是一个动作，但其实分成三件事：

1. 生成平台无关的发送请求
2. 适配具体平台 sender
3. 处理媒体、失败和幂等

如果把这些揉成一团，OneBot、Telegram、QQ Official 的差异会很快把主链路拖乱。

## NotificationService

`NotificationServiceImpl` 是 scheduler/legacy 入口到应用 dispatcher 的桥接层。

### 正常流程

1. 接收 feed 更新
2. 遍历 entries
3. 组装正文、媒体、raw_xml
4. 调用 `NotificationDispatcher.dispatch_to_feed_subscribers()`

### 错误通知

如果 feed 抓取失败，会直接对相关订阅发送错误通知，而不是走普通条目链。

## Sender Provider / Adapter

### `InfrastructureMessageSenderProvider`

它根据平台名返回一个适配后的 sender：

- Telegram
- OneBot / aiocqhttp
- QQ Official
- Weixin OC

### 平台策略

provider 会同时解析 sender strategy：

- `telegram` -> Telegram 策略
- `aiocqhttp` / `onebot` -> OneBot 策略
- `qq_official` / `qqofficial` / `qq` -> QQ Official 策略

### Adapter 作用

`InfrastructureMessageSenderAdapter` 把应用层 `SendRequest` 转成基础设施层 sender 能懂的结构。

这样做是为了：

- 保持应用层不依赖具体平台实现
- 统一 sender 返回值
- 统一错误与重绑语义

### 推送排版策略

`style` 的枚举语义见 [`domain-model.md`](./domain-model.md#推送排版策略)。sender 层只负责按该策略选择平台发送结构。

### QQ Official / Weixin OC 顺序发送

`qq_official` 和 `weixin_oc` 不再统一走默认整条 chain 策略。它们在 sender adapter 内部按平台能力处理：

- QQ Official 单图 + 文本合成一条 `Image + Plain`。
- QQ Official classic 中的视频/多媒体仍按媒体优先、文本最后拆发。
- QQ Official original 按 layout fragments 尝试图片 + 后续文本合链，视频仍独立。
- Weixin OC 始终逐条发送，original 只影响顺序，不合并图文。

这样做是为了避开平台对多媒体图文链的吞文本问题，同时保留 QQ Official 单图图文链的可读性。

如果中途某个媒体失败，sender 不会立刻停止，而是继续发送剩余媒体和最终文本。最终 `SendResult.ok=False`，`transient` / `needs_rebind` 聚合所有失败结果，`detail` 带有 `partial send` 语义。最终文本只追加失败媒体的原始链接，不追加成功媒体链接。

### Markdown 文本发送

RSS 文本格式化层支持平台感知的轻量 Markdown 输出。默认平台仍保持纯文本；Telegram 的文本内容可渲染为标题加粗、可点击 via 链接等保守 Markdown。

QQ Official 的运行时开关在 `sender_strategies.platform_strategies` 的 `qq_official_strategy.markdown_mode`：

- `auto`：预留平台默认策略。
- `force`：预留强制 Markdown 策略。
- `plain`：纯文本策略。

QQ Official sender 必须通过 AstrBot `MessageChain.use_markdown_` 控制 Markdown，不能绕过 core 手写 botpy payload。当前主动推送链路临时统一生成纯文本并显式关闭 QQ Official Markdown，避免 `**标题**`、`[链接](链接)` 等 Markdown 原文直接暴露给用户；待 AstrBot core 对主动推送的消息级 Markdown 行为稳定后，再恢复三态策略。

Telegram 不新增插件侧开关。插件只优化 Plain 文本文案，AstrBot Telegram adapter 会对 Plain 文本走 MarkdownV2 转换；媒体 caption Markdown 不是当前插件承诺面。

### OneBot 经典与原始顺序

OneBot auto/classic 使用合并转发，节点名优先使用 feed title。合并转发失败后会回退为纯文本 Nodes。OneBot original 不使用大合并转发包，而是按 layout fragments 逐条发送图文片段，适合 AI 日报这类多图长文。

### Telegram 大图片

Telegram Bot API 对 photo 有大小上限。发送前如果本地图片文件超过内置 photo 阈值，Telegram sender 会把它改为文件组件发送，避免平台把大图按 photo 拒绝。这个降级只改变发送组件类型，不改变原始媒体 URL 和失败历史记录。

### m3u8 / HLS 视频

媒体发送始终先预下载到本地成功缓存；下载失败不会写入失败缓存，下一次推送会重新尝试。m3u8/HLS 链接会交给 FFmpeg 合并为 MP4，并沿用标准化后的 `http_config.proxy` 作为 FFmpeg HTTP 代理参数；裸 `host:port` 会按 `http://host:port` 处理。`http_config.media_timeout` 控制媒体预下载和 FFmpeg 下载超时，上限 1800 秒。下载流程不只检查文件非空，还会用本地文件头/`filetype` 探测真实媒体类型与缓存后缀，再用 `media_integrity` 验证图片头/可选 Pillow 完整性，并用 ffprobe 校验视频流与时长；校验失败会删除坏缓存，并沿用媒体下载失败路径，让 sender 追加原始链接或按平台能力降级，而不是缓存坏文件。

OneBot 默认优先发送本地视频文件，避免 NapCat/OneBot 端自行拉取远程 m3u8 失败。QQ Official 默认不按媒体数量预先降级为文件，图片/视频会先按平台媒体组件发送，真实发送失败后再按内置策略降级并在文本中暴露失败媒体链接。平台限制和默认策略的常量归属见 [`domain-model.md`](./domain-model.md#常量归属)。

## 媒体 fingerprint

### `HttpMediaFingerprintService`

这个服务会下载媒体 URL 的小样本，然后算 `sha256`。

### 算法步骤

1. 限制 URL 数量
2. 只接受 http/https
3. 发起短超时请求
4. 逐块读取响应
5. 超过 `max_bytes` 就放弃
6. 对内容做 `sha256`

### 返回值形式

返回值统一加前缀：

- `media:<sha256>`

### 为什么不用直接拼 URL

因为很多媒体链接：

- 可能是临时签名 URL
- 可能会重定向
- 可能同内容不同地址

下载少量字节算内容 hash，更适合做“媒体是否相同”的判断。

## 失败与回退

- 非 http/https -> 直接忽略
- 响应非 200 -> 跳过
- 超过大小上限 -> 跳过
- 下载异常 -> debug 级别记录并跳过

也就是说，media fingerprint 是增强能力，不是发送门槛。

## 设计理由

这一层的原则是：

- sender 适配不能侵入业务规则
- sender adapter 可以处理平台专属发送次数与顺序
- fingerprint 不能阻断推送
- 失败要能回退到最小可发内容
