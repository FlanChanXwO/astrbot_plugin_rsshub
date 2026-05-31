# 文本格式化与组件排序

## 负责什么

当前格式化链可以分成两个层面：

1. `EntryTextFormatter`
   - 负责把 entry 整理成最终文本
2. `MessageComponentSorter`
   - 负责把媒体、文本、失败链接整理成平台发送前的统一组件顺序

## 为什么拆成两层

文本清洗和平台排序不是同一个问题：

- 文本格式化关心标题、正文、via、作者、标签
- 组件排序关心媒体与文本在不同平台上的发送顺序

把它们拆开后，改 onebot 排序不会碰正文格式，改 via 逻辑也不会影响 sender 组件顺序。

## EntryTextFormatter 算法

主要步骤：

1. `clean_text`
   - 走 `HTMLParser`
   - 提取纯文本
   - 去掉 `[视频]` / `[音频]` 占位
2. 去重标题
   - 如果 body 和 title 本质相同，就清空 body
3. 应用长度限制
4. 按配置决定是否显示：
   - title
   - tags
   - via
   - author

## 为什么 via 要单独处理

`via` 是兼容历史行为的重要部分。它承担两类信息：

- 条目链接
- feed 来源

同时还要兼容：

- 完全禁用 via
- 仅链接
- source 缺失
- author 追加但不出现 `via  |` 这种坏尾巴

所以它被单独抽成 `_build_via_suffix()`，而不是内联拼字符串。

## MessageComponentSorter 算法

排序目标是平台无关组件：

- `media`
- `text`
- `tail`
- `failed_url`

核心规则：

- 默认媒体优先于文本
- onebot-like 平台把 `tail` 里的音频/文件也尽量放在媒体区
- 文本主体统一放后面

注意：`MessageComponentSorter` 只负责排序，不负责决定“一条消息拆成几次发送”。平台是否需要拆批发送属于 sender adapter 的职责。

## 推送排版策略

`style` 字段现在表示推送排版策略：

- `0=auto`：自动选择平台经典发送方式，例如 OneBot 使用合并转发。
- `1=RSSRT`：保留给 RSSRT 排版策略。
- `2=original`：优先使用 HTML/XML 解析树生成的 layout fragments，尽量按原始顺序发送图文片段。

旧 `flowerss` 语义已经废弃，迁移时会重置为 classic。

## 表格图片语义

HTML `<table>` 解析时会先尝试走轻量转图链路：

- `HTMLParser._parse_table()` 调用 `infrastructure.rendering.TableImageRenderer`。
- Renderer 使用 `BeautifulSoup/lxml` 读取 `caption`、`thead`、`tbody`、`tr`、`th`、`td`，并基础处理 `rowspan` / `colspan`。
- 图片用 `Pillow` 绘制为统一聊天卡片风格，不做网页 CSS 高保真截图。
- 字体按 `RSSHUB_TABLE_FONT_PATH` 环境变量、`RSSHUB_TABLE_FONT_DIR` 环境变量、运行时下载目录（`data/fonts/`）、`assets/fonts/` 的顺序查找。插件启动时自动从 jsDelivr CDN 下载 Noto Sans SC 子集 OTF 到持久化数据目录，SHA256 + 大小双重校验，下载失败时表格回退为 `A | B | C` 纯文本（不使用 Pillow 默认字体）。用户也可通过环境变量指定自定义字体，或把 `.ttf`/`.otf`/`.ttc` 放入 `assets/fonts/` 或运行时字体目录。
- 成功后正文树里放入 `GeneratedImageContent`，`layout` 中生成带 `local_path` 的 image fragment；original style 不再把 `[表格已转为图片]` 作为可见文本片段发送，表格纯文本只作为图片缺失或发送失败时的内部 fallback。
- 文本格式化会按 `display_media` 决定是否走表格转图：正常显示媒体时移除短占位以避免重复刷屏；关闭媒体时保留 `A | B | C` 文本 fallback。

表格图片按规范化表格模型计算 sha256，并保存为 `cache/table_images/table_<hash>.png`。同一表格重复推送会复用同一张图，缓存写入使用唯一临时文件避免并发同 hash 互相覆盖。空表格、坏 HTML 或渲染异常会保留原有 `A | B | C` 文本 fallback，不阻断 RSS 推送。

## 为什么 OneBot 维持“媒体在前，文本在后”

这是当前实际平台兼容性做出来的结果，不是抽象美感选择：

- OneBot 合并转发对媒体节点放前面更稳定
- 文本尾巴与 via 放后面更符合当前实际发送表现
- 这也和插件现有历史表现保持一致

因此项目明确把它作为兼容规则保留下来。

## 失败链接追加策略

失败链接只在失败面向场景追加：

- sender 发送失败回退文本
- history 记录失败时

正常成功态不追加，避免正文被原始媒体链接污染。

`qq_official` / `weixin_oc` 是平台特例：QQ Official 单图可与文本合发，视频和多媒体场景仍由 sender 拆批；Weixin OC 不支持图文同发，只能逐条发送。OneBot auto/classic 合并转发失败后会回退为纯文本 Nodes，original 排版不使用大合并转发包。

## 标题去重边界

正文开头与标题完全重复时，formatter 只会在标题实际显示的情况下剔除重复正文标题。若用户关闭标题显示，正文必须保持完整；这避免 bsky 等源把正文首句同时写入 `title` 和 `description` 时，推送只剩 hashtag 或后半段正文。
