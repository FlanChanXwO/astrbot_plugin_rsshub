# Feed 轮询与增量识别

## 负责什么

`FeedPollingService` 是“轮询一条 Feed 并生成可分发条目”的统一入口。scheduler、手动刷新、按组选定订阅刷新，最终都应该收敛到它，而不是各自复制一套抓取逻辑。

## 为什么做成统一服务

轮询链路最容易出现的历史问题有三类：

- 条目抓取和测试推送的内容清洗不一致
- 去重算法在不同入口各写一份
- 首次初始化、304、失败返回的语义不一致

统一服务的价值是：无论入口是谁，Feed 的读取、去重、metadata 更新和 dispatch 输入构造都只维护一份。

## 主流程图

下面的 Mermaid 图展示轮询主路径。异常、兼容指纹和历史窗口合并的细节仍以正文算法说明为准。

```mermaid
flowchart TD
  A["Scheduler / 手动刷新 / 指定订阅刷新"] --> B["FeedPollingService"]
  B --> C["构造条件请求头"]
  C --> D{"Feed 是否变化"}
  D -->|"304 / 无新内容"| E["返回无变化结果"]
  D -->|"200 / 有内容"| F["解析 RSS / Atom / JSON Feed"]
  F --> G{"解析成功"}
  G -->|"否"| H["返回 parse_error"]
  G -->|"是"| I["更新 Feed metadata"]
  I --> J["生成 entry 指纹组"]
  J --> K{"是否新条目"}
  K -->|"否"| L["合并历史窗口"]
  K -->|"是"| M["构造 dispatch 输入"]
  M --> N["交给 NotificationDispatcher"]
  N --> P["只确认 success / 明确 skipped"]
  P --> L
  L --> O["保存 Feed 状态"]
```

## 输入与输出

### 主要输入

- `feed_id`
- `notify_new_entries`
- `subscription_ids`（可选）
- `verbose`

### 主要输出

- `FeedPollingResult`
  - 是否成功
  - 新增条目数
  - 实际分发数
  - 是否首轮跳过历史

## 算法步骤

### 1. 条件抓取

服务先根据 feed 当前状态构造条件请求头：

- `If-None-Match`
- `If-Modified-Since`

这样能尽量让 304 成为“无变化”的快速路径，减少重复解析。

### 2. 解析 feed 与 entry

抓取成功后：

- 用 parser 解析 RSS/Atom/JSON Feed
- 更新 feed 的 title、etag、last_modified

如果解析失败，直接返回 `parse_error`，不做部分更新。

JSON Feed 只支持标准 1.0 / 1.1 文档；普通 JSON API 不会被当作 Feed。为了兼容现有 XML scope handler 与 push history，JSON Feed 条目的 `raw_xml` 会合成为单个 RSS `<item>` 片段，这不是上游原始 XML。

### 3. 增量识别

增量识别不是只算一个 hash，而是“分组指纹”：

- 稳定身份 hash：优先 `id / entry_id / guid / link`
- 内容 hash：`title + link + summary`
- 兼容 hash：
  - upstream crc32
  - legacy crc32
  - entry identity

这样做的原因是：

- 只靠 link 会被 query 参数或无 link 源击穿
- 只靠 summary/title 会被轻微改文误判
- 只靠单一稳定 id 会被不规范上游源击穿

所以现在的策略是“稳定身份优先，兼容 hash 兜底”。

### 去重指纹的真实生成方式

上面说的是概念层，这里补代码里的真实生成规则。当前实现对应 `FeedPollingService._hash_entry()`。

单个条目不会只生成一个 key，而是生成一个“指纹组”：

1. 稳定身份指纹 `sid:`
2. 内容指纹 `sha256(title + link + summary)`
3. 兼容指纹：
   - upstream `crc32`
   - legacy `crc32`
   - 原始 identity 值（`guid / entry_id / id / link` 之一）

#### 稳定身份指纹 `sid:`

稳定身份材料按下面顺序选择：

1. `id`
2. `entry_id`
3. `guid`
4. `link`
5. `title`
6. `summary / description / content`

生成材料时会带版本前缀，例如：

- `v3|id=post-123`
- `v3|link=https://example.com/posts/123`
- `v3|title=新图发布`
- `v3|summary=正文前 256 字符`

然后对整段材料做 `sha256`，最终存成：

- `sid:<sha256>`

这个 `sid:` 会在历史窗口合并阶段优先作为“同一条 entry”的主判断依据。

#### 字段规范化细节

指纹生成前，字段不会直接拿原值，而是会先做规范化。

##### `link`

- 优先取 `entry.link`
- 如果 `link` 为空，则回退到 `guid`
- 如果是相对地址且存在 `feed_link`，先用 `urljoin(feed_link, link)` 补全
- 再剥离 tracking query 参数

默认会剥离的参数包括：

- `utm_source`
- `utm_medium`
- `utm_campaign`
- `utm_term`
- `utm_content`
- `utm_id`
- `gclid`
- `fbclid`
- `mc_cid`
- `mc_eid`
- `spm`
- `ref`
- `ref_src`

##### `title / summary / content`

文本规范化步骤：

1. `html.unescape`
2. 折叠连续空白为单个空格
3. `strip()`
4. 转小写
5. 截断到上限

其中：

- 通用文本规范化默认上限是 `1024`
- `summary` 在稳定身份退化时只取前 `256` 字符
- `summary` 在内容指纹里取前 `512` 字符

##### `id / guid / entry_id`

- 只做 `strip()`
- 不转小写
- 最长保留 `1024` 字符

这样可以尽量保持上游标识的原始稳定性，避免大小写变化带来额外歧义。

#### 内容指纹

无论有没有稳定身份，都会额外生成一个内容指纹，材料固定为：

- `v3|title=<title>|link=<link>|summary=<summary前512字符>`

它主要用来处理没有规范 `guid/id` 的源。

#### 兼容指纹

兼容指纹保留旧实现和上游现有行为的痕迹，作用是尽可能命中旧历史，避免升级后大面积重推。

所以一个条目的最终指纹组，实际可能长这样：

```text
[
  "sid:9b7c7f...",
  "2a4d9c...",
  "8f3e1a",
  "38472615",
  "https://example.com/post/123"
]
```

### 为什么还保留 upstream / legacy 指纹

这里不是“新算法已经不需要旧算法”，而是为了兼容历史数据和旧版行为。

- `upstream crc32` 兼容一些上游源已经写好的习惯性 hash
- `legacy crc32` 兼容插件旧版本已经落库的去重记录
- `entry_identity` 兼容一些只靠 `guid / entry_id / id / link` 的历史数据

所以当前策略是“新指纹主导，旧指纹陪跑”，尽量避免升级后把老条目重新推一遍。

### 去重例子

#### 例 1：规范 RSS 条目

输入：

- `guid = post-123`
- `link = https://example.com/posts/123?utm_source=rss`
- `title = 新图发布`
- `summary = ...`

结果：

- 稳定身份优先使用 `guid`
- `link` 参与内容指纹时会先做标准化
- 即使标题后续被轻微修改，只要 `guid` 不变，仍会被识别为同一条

#### 例 2：没有 guid，但有 link

输入：

- `guid = ""`
- `id = ""`
- `link = https://site.example/item/42?utm_source=x&utm_medium=y`
- `title = 更新啦`

结果：

- 稳定身份退化为 `v3|link=<normalized-link>`
- `utm_*` 这类 tracking query 参数会先被移除
- 同一条目仅因追踪参数不同，不会被误判成新内容

#### 例 3：没有 guid，也没有 link

输入：

- `title = 今日汇总`
- `summary = A / B / C`

结果：

- 稳定身份继续退化到 `title`
- 若 `title` 也缺失，再退到 `summary` 前缀
- 这类源天然更脆弱，因此系统会同时保留内容指纹和兼容指纹兜底

### 4. 历史窗口合并

历史不是平铺字符串列表，而是按 entry 分组的 hash groups。

如果本轮需要推送新条目，历史窗口只合并已经确认处理的 entry：

- `success`：已经成功投递，可以推进水位
- 明确规则性 `skipped`：例如 handler skip 或多 BOT 去重，已有审计，可以推进水位
- `pending` / `failed` / dispatcher 异常：不能推进水位，下轮仍应可补推或进入重试

当存在未确认的新条目时，Feed 的 `etag` / `last_modified` 也保持旧值，避免下一轮条件请求直接得到 304，导致未确认条目失去重新解析机会。

合并策略：

1. 先放新条目 groups
2. 再接旧历史 groups
3. 用 `sid:` 稳定身份去重
4. 截断到动态上限

动态上限取决于：

- `hash_history_min`
- `hash_history_multiplier`
- `hash_history_hard_limit`
- 当前条目数

这样做的原因是：

- 小 Feed 不需要无限历史
- 大 Feed 如果只保留很小历史，重复风险会很高
- 上限必须可控，避免数据库持续膨胀

### 5. 首轮初始化跳过历史

当同时满足这些条件时，会触发 bootstrap skip：

- `notify_new_entries = true`
- 确实发现新条目
- 旧历史为空
- `bootstrap_skip_history = true`

这意味着首次建订阅时先建立去重历史，不把旧内容一股脑发出去。

### 6. `minimal_interval` 的真实语义

`minimal_interval` 不是“轮询时如果太小再偷偷修正”的运行时补丁，而是保存期硬限制。

这条语义要求：

- 订阅配置写入时不能保存小于该值的间隔
- 用户/会话默认值如果参与生成订阅生效间隔，也不能绕过该下限
- Web API、命令和管理页对外展示时都应把它理解为持久化边界，而不是仅执行边界

这样做的目的是避免：

- 数据库存进非法过小间隔，后续每个调用方再各自补救
- 不同入口对“1 分钟以下到底算不算合法”出现分裂语义
- 排障时看到已保存值与实际运行值不一致

## dispatch 输入构造

当决定要分发时，每个条目会被整理成统一输入：

- `content`: 已清洗的默认正文
- `media_urls`
- `media_items`
- `entry_guid`
- `raw_entry`

关键点是：

- 默认正文已经去掉 HTML 标签与媒体占位
- `raw_entry` 仍保留原始文本和 `raw_xml`，供 handler 使用；JSON Feed 的 `raw_xml` 是插件合成的 `<item>` 片段

这正是后来“正文不能再从原始 HTML 回退覆盖”的根基。

## 失败与回退

- 抓取异常：`fetch_error`
- 解析异常：`parse_error`
- 304：`not_modified`
- 首轮历史跳过：`bootstrapped`
- 有更新但不分发：允许存在，例如 notify 关闭或未进入 dispatch

这个服务的职责是产出稳定的 polling 结果，不负责解释平台 sender 失败。
