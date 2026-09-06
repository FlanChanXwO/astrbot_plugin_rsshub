# 统一卡片模板与多源聚合投递设计

## 1. 状态与范围

本文是卡片模板化日报与多源聚合订阅（Bundle）的统一实现规格。它约束后续领域、持久化、运行时、公开接口、Plugin Pages、迁移、测试与回滚工作。

本目标引入来源无关的可靠投递内核，供两类 owner 使用：

- 开启卡片的普通 `Subscription`；
- 聚合两个或更多 Feed 的 `Bundle`。

`send_card=false` 的普通 Subscription 保持现有逐条推送路径，不迁移到新批次内核。这样既复用统一能力，又避免无收益地改变稳定路径。

首版明确不做模板市场、在线编辑器、脚本沙箱、cron、成员权重、跨 Bundle 去重、Bundle 导入导出、现有普通订阅迁移或共享 entry archive。

## 2. 成功标准

1. Subscription 与 Bundle 均持有 `send_card`、`template_id`、`card_send_original_content`；默认值分别为 `false`、`null`、`false`，卡片配置不属于共享 Feed。
2. Subscription 可把一次发现的全部新增条目渲染成一张卡片；Bundle 可把多个 Feed 的新增条目聚合为 RSS 2.0 文档，再输出普通内容或卡片。
3. 模板包以 `metadata.yaml` 声明版本、作者、目标类型和适配 Feed 系列，支持内置包、ZIP 上传和 HTTP(S) 下载。
4. handler 总在模板之前运行；模板只读取 handler 后的稳定快照。重试不重新运行 handler，也不读取后来覆盖的模板。
5. 一个可靠批次可产生一条 card 与一条或多条 standard 输出历史；card 是 standard 的前置门，失败时不自动回退普通推送。
6. 发送失败期间继续把新内容可靠写入 owner 私有 inbox，但同一 owner 不创建第二个未确认批次；不静默截断、不按时间清理 backlog，也不伪造成功。
7. Bundle 的命令、LLM tools、Web API、Plugin Pages、历史、重试、显式丢弃和删除保护完整可用；普通订阅保持兼容。
8. 所有代码任务实际执行 TDD Red → Green → Refactor，并通过相称的单测、集成、ruff、前端测试、真实浏览器和可用环境下的 T2I 冒烟。

## 3. 核心领域决策

### 3.1 卡片配置归属与模式

卡片配置属于具体消费者，不属于共享 Feed：

- `send_card=false`：忽略 `template_id` 与 `card_send_original_content`，走标准路径；
- `send_card=true, card_send_original_content=false`：只发卡片；
- `send_card=true, card_send_original_content=true`：先发卡片，再发标准内容。

保持两个布尔字段，不改为枚举。开启卡片时，`template_id` 必填且模板必须匹配当前 owner。应用服务负责这一跨实体校验。Pages 只提供严格过滤后的模板候选，不提供手工 ID 输入。

### 3.2 Handler 顺序与消费语义

Subscription 对批次内每个 entry 运行现有 entry handlers；Bundle 对完整 RSS channel 运行独立的文档级 handlers。模板只读取 handler 后的 JSON-safe 数据。

handler 删除或过滤的输入仍保留在批次输入集合中；批次成功、明确 skip 或显式 discard 时才消费。输入消费身份始终来自原始 inbox item key，不从 handler 输出反推。

provider 不可用、非法 JSON/XML 或 handler 异常沿用现有可观测 fallback。模板渲染失败不回退到普通推送。

### 3.3 批次与输出历史

新增来源无关的 `DeliveryInboxItem` 与 `DeliveryBatch`。owner 类型只允许 `subscription|bundle`。

`push_history` 是批次下的输出记录，不是批次本身。一个批次可以有一条 card 历史及一条或多条 standard 历史：

- 单 Feed 标准输出仍是一条 entry 一条历史；
- Bundle 对每个 target 产生一条聚合 standard 历史，并在启用卡片时各产生一条 card 历史；
- card 失败时所有 standard 输出保持 `waiting`；
- card 成功后，Subscription 的标准条目彼此独立尝试，一条失败不阻断其他条目；
- 自动和人工重试仅处理未完成输出，成功输出绝不重复发送。

## 4. 领域模型与持久化

### 4.1 Subscription、Bundle 与成员

`rsshub_sub` 以加法迁移新增：

- `send_card BOOLEAN NOT NULL DEFAULT FALSE`；
- `template_id VARCHAR NULL`；
- `card_send_original_content BOOLEAN NOT NULL DEFAULT FALSE`。

`rsshub_bundle` 使用以下明确契约：

| 字段 | 类型与默认值 | 语义与约束 |
| --- | --- | --- |
| `id` | 自增整数 | 主键 |
| `user_id` | 非空字符串 | owner；外键沿用现有用户生命周期约束 |
| `name` | 非空字符串 | 同一 `user_id` 下唯一 |
| `target_sessions` | 非空 JSON 字符串列表 | 保持输入顺序并去重；每项是现有 `unified_msg_origin`，一次配置变更对所有目标全有或全无 |
| `state` | 整数，默认 `0` | 仅允许 `0=disabled`、`1=enabled` |
| `interval` | 正整数分钟 | 固定滚动周期，复用现有 interval 写入校验，不使用继承值 |
| `next_check_time` | 可空 UTC 时间 | 启用时设为当前时间；每次到期采集尝试后，从原计划点前推若干完整 interval，取首个晚于当前时间的计划点，避免按完成时间漂移 |
| `notify`、`send_mode`、`length_limit`、`display_author`、`display_via`、`display_title`、`display_entry_tags`、`style`、`display_media` | 与 Subscription 相同的整数及 `INHERIT_VALUE` 默认值 | 复用现有用户/全局继承解析和标准输出语义 |
| `handlers` | JSON 列表，默认 `[]` | Bundle 文档级 handlers；不复用 entry handler 输入契约 |
| `send_card` | 布尔，默认 `false` | 是否生成 card 输出 |
| `template_id` | 可空字符串 | 开启卡片时由应用服务校验非空、归属和匹配 |
| `card_send_original_content` | 布尔，默认 `false` | card 成功后是否继续发送聚合 standard 输出 |
| `created_at`、`updated_at` | UTC 时间 | 审计时间 |

启用 Bundle 时必须至少有两个不同 Feed，并且 `target_sessions` 非空；停用时可暂存少于两个成员。启用和配置修改均通过同一应用校验，不允许 ORM 或接口各自发明不同规则。

`rsshub_bundle_feed` 保存 `bundle_id`、`feed_id`、`position`、私有 `entry_hashes`、`etag`、`last_modified`、最近检查状态和时间。`(bundle_id, feed_id)` 与 `(bundle_id, position)` 均唯一；position 是从 0 开始的连续整数，由成员原子更新用例维护。删除 Bundle 前必须先通过未解决批次与 inbox 保护，然后成员随 Bundle 删除；被成员引用的 Feed 不得物理删除。相同 Feed 可被普通 Subscription 和多个 Bundle 引用，各消费者水位完全隔离。

### 4.2 Inbox

新增 `rsshub_delivery_inbox`：

- owner：`owner_type`、`owner_id`；
- 来源：`feed_id`、可空 `bundle_feed_id`、成员 position 快照；
- 身份：`item_key`、`hash_group`；
- 成批：`discovery_key`，标识同一 owner 在一次成功发现事务中写入的集合；
- 内容：JSON-safe entry payload、`raw_xml`、`media_items`；
- 时间：published、updated、discovered；
- 认领：可空 `batch_id`。

唯一键由 owner、来源与 `item_key` 组成，保证重复轮询和并发调度幂等。`hash_group` 保存同一 entry 的稳定身份哈希集合，不承担成批职责；`discovery_key` 由 owner、来源和本次按稳定顺序排列的 item keys 确定性生成，因此重复执行同一发现得到同一个 key。Bundle 的 inbox 写入与成员水位推进在同一事务中完成；卡片 Subscription 由一次普通 Feed 抓取结果向各自私有 inbox 可靠扇出。

### 4.3 DeliveryBatch 与 PushHistory

新增 `rsshub_delivery_batch`，保存 owner、`pending|confirmed|discarded` 状态、目标和配置快照、模板快照、handler 后文档快照、创建时间与确认时间。

`rsshub_push_history` 以加法迁移新增：

- 可空 `batch_id`；
- `output_kind=card|standard`；
- `output_order`；
- 可空 JSON `source_context`；
- Bundle 来源关联或不可变快照字段。

输出状态支持 `waiting|pending|retrying|success|failed|stopped|skipped|discarded`。只有所有配置输出均为 `success|skipped`，批次才确认。`failed`、`stopped`、`waiting` 均保持 pending。

显式 discard 将当前批次的未完成输出标为 discarded，并消费本批已认领输入；未认领 backlog 不受影响。

Bundle 的目标列表固化进批次快照。card 前置门按 target 独立生效：某个 target 的 card 失败只让该 target 的 standard 保持 waiting，不阻止其他 target 继续；但批次确认仍要求所有 target 的全部配置输出都达到 `success|skipped`。人工重试按原 history 定位 target，不向已成功 target 重发。

### 4.4 一致性与删除保护

- 同一 owner 最多有一个未确认批次；创建与认领必须在仓储事务中保证，而非仅靠进程锁。
- 未解决批次存在时，Subscription 不得关闭卡片或取消订阅，Bundle 不得删除。
- Bundle 成员存在已认领或未消费 inbox 时不得移除；成员重排仅影响未来批次。
- unresolved history 不得单删、批量删、cleanup 或 clear；批量操作返回逐项跳过详情。
- reconciliation 只暴露并修复可证明的不一致状态，不把异常静默改成成功。

## 5. 模板包与渲染

### 5.1 固定包结构

```text
metadata.yaml
template.html
partials/  # 可选
assets/    # 可选，固定目录
```

`metadata.yaml` 必须包含：

- `id`：格式为 `astrbot_plugin_rsshub_card_<slug>`；
- `name`；
- `version`：SemVer；
- `author`；
- `description`；
- `repository`；
- `targets`：非空且仅含 `feed|bundle`；
- `feed_patterns`：可选正则列表，空列表表示任意来源。

不增加 `schema_version`，不允许自定义 assets 路径。Subscription 匹配自身规范化 Feed URL；Bundle 在 patterns 非空时要求全部成员 URL 均匹配。正则使用大小写不敏感的 `search`。

### 5.2 安装、覆盖与存储

模板安装到 `get_plugin_data_dir("card_templates")`；历史 HTML/PNG 保存到 `get_plugin_data_dir("card_artifacts")`。数据库只保存受控引用和不可变元数据。

ZIP 必须先在临时目录校验，拒绝路径穿越、绝对路径、符号链接、非法 YAML、非法正则和缺失入口。同 ID 采用原子覆盖，任一阶段失败均保留旧包。被 Subscription 或 Bundle 引用的模板不得删除；覆盖不影响已固化批次。

URL 只接受 HTTP(S)。HTTPS 不提示；HTTP 必须由 Pages 显示警告并在确认后发送 `allow_insecure_http=true`；其他协议前后端均拒绝。首版沿用已确认的高信任管理模型，不额外加入 SSRF 白名单或无依据下载限制。

### 5.3 Jinja 上下文和边界

只暴露 post-handler 的 JSON-safe 数据：

- `source`；
- 单 Feed 的 `feed`；
- Bundle 的 `bundle` 与有序 `feeds`；
- `entries`；
- `document.text`、`document.rss_xml`；
- `template`；
- `meta`；
- 仅能读取包内 assets 并生成 data URI 的 helper。

Jinja 开启自动转义和 StrictUndefined，支持循环、条件、表达式、宏、include 与固定 filters；不暴露宿主对象、文件系统或任意 Python 执行。`content_html` 需要显式 `|safe`。

公共上下文采用稳定的最小 JSON schema，允许以后加字段但不得改变既有字段含义：

- `source: {type, owner_id}`，其中 type 为 `feed|bundle`；
- `feed: {id, title, link}`，仅 Feed owner 存在；
- `bundle: {id, name}` 与 `feeds: [{id, title, link, position}]`，仅 Bundle owner 存在且 feeds 按 position 排序；
- `entries: [{item_key, feed_id, title, link, author, published, updated, summary, content_html, tags, media_items}]`，时间为可空 ISO 8601 字符串，缺失文本用空字符串，列表字段用空列表；
- `document: {text, rss_xml}`，均为 handler 后字符串；
- `template: {id, name, version, author}`；
- `meta: {batch_id, rendered_at}`，其中 rendered_at 为 UTC ISO 8601 字符串。

Subscription 的 entries 保持一次 discovery 的来源顺序；Bundle 先按成员 position，再按成员内发布时间降序排列，无时间条目保持抓取顺序。模板只能依赖上述值和固定 filters/helper。

管理与预览界面必须明确提示：模板采用高信任浏览器模型，作者提供的脚本及网络访问具有风险。运行时依赖明确使用 `jinja2>=3.1.6`；渲染复用 AstrBot `html_renderer`，不新增 Playwright/Chromium 运行时。

## 6. 运行时数据流

### 6.1 卡片 Subscription

1. Feed 沿用现有抓取、解析与完整 `new_entries` 计算。
2. `send_card=false` 的 Subscription 继续逐条标准路径。
3. 每个卡片 Subscription 将完整新增集合写入自己的 inbox，不受 `history_entry_limit` 截断；同一次 Feed 发现为每个 owner 生成稳定的 `discovery_key`，唯一键吸收重复轮询。
4. owner 没有未确认批次时认领 inbox；逐 entry 运行其生效 handlers，并固化模板和 handler 结果。
5. 先渲染并发送 card；如配置原文，再按现有 `history_entry_limit`、send_mode、显示字段、媒体和排版逐条发送 standard。
6. 失败交给持久化批次重试；后续发现继续写入 inbox。

普通 Feed 水位仅在现有普通订阅满足原确认条件且所有卡片 Subscription 的 inbox 已可靠持久化后推进。普通路径的既有语义不变。

Subscription 批次严格保持“一次发现”边界：没有未确认批次时，只认领最旧 `discovery_key` 下的全部未认领条目；该批确认或 discard 后，再为下一个 discovery 建批。pending 期间的新发现使用新的 discovery key 入箱，不并入现有批次，也不与其他轮次合并。

Subscription 不另设私有采集水位。新建卡片 Subscription 只接收其创建后由共享 Feed 计算出的新增条目；若 Feed 本身首次抓取且全局 `bootstrap_skip_history=true`，沿用既有首次初始化行为：历史条目不写任何 Subscription inbox，Feed hashes 与 HTTP validators 正常持久化。若该配置为 false，则首次抓取条目作为一个 discovery 写入所有当时生效的卡片 Subscription inbox。Feed 水位和所有扇出 inbox 必须在同一事务结果中提交；任一 inbox 写入失败时不推进共享水位或 validators。

### 6.2 Bundle

1. Scheduler 按固定滚动周期查询到期 Bundle；未确认批次不阻止成员采集。
2. 按 position 串行抓取成员，使用 BundleFeed 私有条件请求和指纹水位。单个成员失败不推进其水位，也不阻断其他成员。
3. 成功发现与对应水位在同一事务写入通用 inbox。
4. 无未确认批次时按成员顺序认领；每成员应用现有 `history_entry_limit`，不设置 Bundle 总量上限，剩余 backlog 留给下一批。
5. 使用结构化 XML API 构建 RSS 2.0 channel，运行 Bundle 文档级 handlers，再创建输出历史并进入公共输出编排器。
6. filter 拒绝或产生合法空 RSS 时，配置输出记为 skipped 并确认批次。

Bundle 没有待确认批次时，从所有未认领条目构造下一批：按成员 position 依次选择，每个成员最多取现有 `history_entry_limit` 条，不设置 Bundle 总量上限。这里允许合并多个采集轮次，因为 Bundle 的产品边界是“当前各成员 backlog 的聚合”，而不是单次 discovery；每个 item 仍保留 discovery_key 供审计。

新 BundleFeed 的首次成功 200 响应沿用全局 `bootstrap_skip_history`：为 true 时，不写 inbox，只在同一事务初始化该成员全部 entry hashes、etag、last_modified 和检查状态；为 false 时，把响应中的全部条目写入 inbox，并在同一事务推进相同水位。首次 304 不视为初始化完成；失败或事务回滚均保持成员未初始化。该规则只作用于新增 BundleFeed 的私有水位，不读取或修改共享 Feed 水位。

### 6.3 重试和快照

- HTML 成功而 PNG 失败时复用 HTML；发送失败时复用 PNG。
- 模板、handlers、成员和配置修改仅影响未来批次。
- 沿用现有自动重试配置，不增加新的重试次数、超时、容量或 backlog 上限。
- 自动重试耗尽后保持可观测的 pending/failed 状态，等待人工重试或显式 discard。

## 7. 应用接口

### 7.1 模板 API

- `GET /templates`
- `GET /templates/options?owner_type=subscription|bundle&owner_id=<id>`
- `POST /templates/install`：接收 multipart `archive` 或 JSON `{url, allow_insecure_http}`
- `POST /templates/preview`：JSON `{owner_type, owner_id, template_id}`；按 owner 读取当前 handlers 和来源，验证模板匹配后非持久化抓取并返回 `{png_base64, template, source_summary}`；不得写水位、inbox、batch 或 history
- `POST /templates/delete`：JSON `{template_id}`；返回删除结果或带活动引用详情的冲突错误

所有接口沿用现有 Dashboard 管理权限、响应封装与 owner 归属校验。

### 7.2 Subscription 与 Bundle 接口

Subscription 实体、DTO、仓储、导入导出及 `POST /subscriptions/update` 增加三个卡片字段。`/sub_set` 与 `rss_set_subscription_option` 只开放两个布尔项，不允许自由填写 `template_id`，也不新增聊天模板选择命令。

Bundle 命令组及 `/聚合订阅` 别名支持 `create/list/show/add/remove/move/set/state/test/retry/discard/delete`。多个 target 的创建和修改必须全有或全无，管理员 test 不产生正常业务副作用。

LLM tools 为 `rss_bundle_create/list/get/update_members/set_option/set_handlers/set_state/delete`；高风险的 test、retry、discard 不向 LLM 暴露。Web API 使用平铺 bundles 路由；现有 `POST /push-history/retry` 扩展为批次感知，新增 `POST /delivery-batches/discard`。

Bundle Web API 的最小契约如下；所有写接口使用 JSON，所有 ID 为整数：

| Method / path | 请求 | 行为 |
| --- | --- | --- |
| `GET /bundles` | 既有分页/keyword 查询参数 | 返回当前管理范围内的 Bundle 摘要 |
| `GET /bundles/detail?id=<id>` | query `id` | 返回 Bundle、成员、backlog 和未确认批次摘要 |
| `POST /bundles/create` | `{name, user_id, target_sessions, interval, feed_ids}` | 以停用状态原子创建；feed_ids 去重后至少两个 |
| `POST /bundles/update` | `{id, name?, target_sessions?, interval?, formatting?, send_card?, template_id?, card_send_original_content?}` | 部分更新；应用层统一验证目标、模板和 unresolved 保护 |
| `POST /bundles/members` | `{id, feed_ids}` | 以数组顺序原子替换成员；应用层执行移除保护 |
| `POST /bundles/handlers` | `{id, handlers}` | 原子替换文档级 handlers，只影响未来批次 |
| `POST /bundles/state` | `{id, state}` | state 仅为 0/1；启用前校验成员、目标和模板 |
| `POST /bundles/test` | `{id, target_session?}` | 管理员真实链路测试，不写业务水位、inbox、batch 或 history |
| `POST /bundles/delete` | `{id}` | 无未解决批次或 inbox 时删除 Bundle 及成员 |

`formatting` 仅接受第 4.1 节列出的现有格式字段。`POST /push-history/retry` 请求为 `{history_id}`，若记录属于批次则只重试该批次尚未完成且当前可运行的输出；`POST /delivery-batches/discard` 请求为 `{batch_id}`。所有接口复用既有成功/错误 envelope，冲突必须返回可机读错误码与阻塞对象详情。

### 7.3 Plugin Pages

- 新增“聚合订阅”和“卡片模板”页；
- Subscription 与 Bundle 侧栏提供两个开关、严格候选下拉、预览及高信任风险说明；无匹配模板时禁止开启并保存；
- Bundle 页面管理已有 Feed、顺序、状态、backlog 和阻塞批次；创建 Bundle 与发现新 Feed 仍走命令或 LLM tools；
- 推送历史按 batch 分组，展示来源、成员、模板快照、输出顺序、input/output XML、handler trace、失败、重试与 discard 状态；
- 内置一个 Juya AI 单 Feed 模板和一个无 patterns 的通用 Bundle 模板。

Pages 必须覆盖 loading、empty、error、确认/取消、活动删除保护、成员排序、阻塞状态和风险提示，并在 desktop/mobile、light/dark、长文本与错误恢复场景真实浏览器验证。

## 8. 错误处理、可观测性与安全

- 日志包含 owner、bundle、bundle_feed、batch、history 标识及采集、积压和输出统计。
- 错误明确区分网络、HTTP、解析、数据库、handler、模板、渲染、sender、用户取消与 discard。
- 不吞异常，不以空结果伪装成功，不自动切换普通推送，不从 handler 输出反推消费身份。
- 模板 ZIP 路径边界、Jinja 对象暴露、XML 结构化构建、Web/命令/LLM 权限和 owner 归属均有负向测试。
- 不新增无依据的成员数、条目数、字符数、节点数、渲染时长、轮询次数、重试次数或 backlog 限制。

## 9. 测试与验收策略

所有代码任务先完整读取并使用 `tdd` skill，实际执行并记录 Red → Green → Refactor：

- 领域与迁移：默认值、约束、旧 SQLite 增量升级及重复启动幂等；
- 仓储与并发：发现/水位原子性、唯一键、批次认领、输出历史、故障回滚和删除保护；
- 模板：metadata、SemVer、targets、正则、ZIP 安全、覆盖、删除、Jinja 上下文、转义、资源与 T2I 边界；
- Feed：普通/卡片混合、多订阅、完整卡片批次、原文限制、handler、失败 backlog 和普通路径回归；
- Bundle：多成员、304、首次跳过、部分失败、排序、XML、handlers、Scheduler、积压、重试和 discard；
- 接口：命令、LLM schema、Web 鉴权、模板 API、预览零副作用和历史保护；
- 前端：Node 测试与真实浏览器 desktop/mobile、light/dark、loading/empty/error、长内容、确认框和 console；
- 集成：Feed/Bundle 从抓取到 handler、card/standard 输出、历史和失败恢复的端到端链路。

验证顺序为目标 pytest → 相关 unit/integration → ruff format/check → Node syntax/tests → 浏览器验收。AstrBot 渲染环境可用时执行真实 T2I 冒烟。交付前使用 `code-review-expert`，每个阻塞发现先补失败测试或最小复现再修复。

## 10. 迁移、交付与回滚

- 所有数据库变化都是加法迁移；旧版本会忽略新表与列。
- 模板覆盖失败必须保留旧包；批次通过不可变快照抵抗模板覆盖和配置变化。
- 每个实现 task 独立提交，只暂存该 task 的文件；禁止 force push、`reset --hard` 和破坏性数据库操作。
- 行为落地后同步架构、领域、仓储、轮询、分发、handlers、命令、AI tools、Web API、Pages、测试、README 与 CHANGELOG。
- 代码回滚以按 task 反向提交为主；数据表和历史保留，避免丢失已采集 inbox 与审计记录。

## 11. 完成定义

只有在以下条件全部满足后才可完成 Goal：

1. 所有普通 task、每三个 task 后的集中检查及追加修复 task 完成；
2. 相关测试、浏览器和可用环境 T2I 证据齐全；
3. 普通订阅回归通过；
4. 迁移、并发、权限、失败恢复、删除保护、文档和回滚完成审查；
5. `code-review-expert` 没有未处理的阻塞发现；
6. 最终候选不存在已知高风险问题。
