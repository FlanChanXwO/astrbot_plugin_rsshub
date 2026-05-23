# RSSHub for AstrBot

<div align="center">

<img src="https://raw.githubusercontent.com/FlanChanXwO/astrbot_plugin_rsshub/master/assets/logo.png" width="400" alt="rsshub"/>

<br/>

<img src="https://count.getloli.com/@astrbot_plugin_rsshub?name=astrbot_plugin_rsshub&theme=rule34&padding=7&offset=0&align=top&scale=1&pixelated=1&darkmode=auto" alt="Moe Counter">

**AstrBot RSS 订阅插件**

[![License: AGPL](https://img.shields.io/badge/License-AGPL-blue.svg)](https://opensource.org/licenses/agpl-3.0)
![Python Version](https://img.shields.io/badge/Python-3.10%2B-blue)
![AstrBot](https://img.shields.io/badge/AstrBot-%E2%89%A54.24.0-green)
![Platform](https://img.shields.io/badge/Platform-Windows%20%7C%20Linux%20%7C%20MacOS-lightgrey)

</div>

---

## 文档导航

- 项目与架构：[`docs/project/README.md`](./docs/project/README.md)
- 开发与贡献：[`docs/dev/README.md`](./docs/dev/README.md)
- 使用文档索引：[`docs/usage/README.md`](./docs/usage/README.md)

> 当前 `usage/` 目录还在逐步拆分中。命令、配置和管理页说明目前仍以本 README 为主。

## 📸 预览

<div align="center">
  <table>
    <tr>
      <td align="center">
        <img src="https://raw.githubusercontent.com/FlanChanXwO/astrbot_plugin_rsshub/master/assets/manual_sub.png" width="400" alt="手动订阅"/>
        <br/>
        <sub>手动订阅</sub>
      </td>
      <td align="center">
        <img src="https://raw.githubusercontent.com/FlanChanXwO/astrbot_plugin_rsshub/master/assets/ai_sub.png" width="400" alt="AI订阅"/>
        <br/>
        <sub>AI订阅</sub>
      </td>
      <td align="center">
        <img src="https://raw.githubusercontent.com/FlanChanXwO/astrbot_plugin_rsshub/master/assets/ai_sub_and_query.png" width="400" alt="AI订阅 + AI查询订阅列表"/>
        <br/>
        <sub>AI订阅 + AI查询订阅列表</sub>
      </td>
      <td align="center">
        <img src="https://raw.githubusercontent.com/FlanChanXwO/astrbot_plugin_rsshub/master/assets/sub_export.png" width="400" alt="导出订阅"/>
        <br/>
        <sub>导出订阅</sub>
      </td>
      <td align="center">
        <img src="https://raw.githubusercontent.com/FlanChanXwO/astrbot_plugin_rsshub/master/assets/sub_import.png" width="400" alt="导入订阅"/>
        <br/>
        <sub>导入订阅</sub>
      </td>
      <td align="center">
        <img src="https://raw.githubusercontent.com/FlanChanXwO/astrbot_plugin_rsshub/master/assets/twitter_push.png" width="400" alt="推特推送"/>
        <br/>
        <sub>推特推送</sub>
      </td>
      <td align="center">
        <img src="https://raw.githubusercontent.com/FlanChanXwO/astrbot_plugin_rsshub/master/assets/pixiv_push.png" width="400" alt="pixiv推送"/>
        <br/>
        <sub>pixiv推送</sub>
      </td>
    </tr>
  </table>
</div>

## ✨ 功能特性

- 📡 **RSS/Atom 订阅** - 支持订阅各类 RSS 源，实时推送更新
- 🔔 **智能推送** - 按订阅级/会话级 interval 调度，同一 feed 在不同会话可使用不同检查间隔
- 🎨 **富媒体支持** - 基于 HTML 结构解析内容（链接、图片、音频、视频、文件、At 组件等）
- ⚙️ **灵活配置** - 订阅级与用户默认级的消息格式选项，会话级默认配置（KV）
- 🤖 **LLM 工具调用** - 支持 AI 订阅、查询、管理等操作
- 🌐 **管理面板** - 基于 AstrBot Plugin Pages 的可视化管理界面，支持订阅、用户、Feed、推送历史、默认订阅设置、schema-driven handler 编辑和 Routes 知识库管理
- 📦 **数据导入导出** - 支持 TOML 格式备份和恢复订阅数据
- 🔄 **失败队列** - 平台连接失败时自动进入队列，恢复后重试推送
- 🤝 **多 BOT 支持** - 单会话多 BOT 去重
- 🔍 **RSSHub 集成** - 支持将 RSSHub Routes 文档同步到 AstrBot 知识库辅助路由检索

---

## 📦 安装

### 方式一：通过 AstrBot 插件市场安装（推荐）

在 AstrBot 管理面板中搜索 `RSSHub` 并安装。

### 方式二：手动安装

1. 克隆本仓库到 AstrBot 的插件目录：
   ```bash
   cd AstrBot/data/plugins
   git clone https://github.com/FlanChanXwO/astrbot_plugin_rsshub.git
   ```

2. 重启 AstrBot 或重载插件

---

## 🛠️ 配置项

> **注意**：AstrBot 配置页仅保留启动级基础设施配置、Routes 知识库和平台发送策略；订阅默认值请前往 AstrBot 面板的 Plugin Pages 管理。

在 AstrBot 管理面板的「配置」页面，找到 `RSSHub` 插件配置：

插件启动时会按当前 `_conf_schema.json` 对实际配置文件做一次轻量自愈：补齐缺失字段、移除已废弃字段、修正常见类型错误，并把下拉选项和滑块数值收敛到合法范围。旧版字段如 `download_media_before_send` 会被清理且不再影响运行时；只有检测到实际变化时才会写回配置文件。

### 基础设施配置 (`basic_config`)

| 配置项 | 类型 | 说明 | 默认值 |
|--------|------|------|--------|
| `proxy` | 字符串 | HTTP/SOCKS 代理地址，留空则不使用代理。例如 `http://127.0.0.1:7890`；填写 `localhost:7890` 这类裸地址时会按 `http://localhost:7890` 处理，媒体预下载和 FFmpeg m3u8/HLS 下载也会使用该代理 | `""` |
| `rsshub_base_url` | 字符串 | 默认 RSSHub 域名，用于路由检索与订阅链接拼接 | `https://rsshub.app` |
| `timeout` | 整数 | 请求超时（秒），获取 RSS 源时的 HTTP 请求超时时间 | `30` |
| `minimal_interval` | 整数 | 最小监控间隔（分钟）。这是保存期硬限制：命令、Web API、Plugin Pages 在写入订阅/默认配置时都不得保存更小值；不是仅运行时兜底。 | `1` |
| `hash_history_min` | 整数 | 去重历史最小保留数量，避免历史回流重复推送 | `500` |
| `hash_history_multiplier` | 整数 | 去重历史增长倍数，动态扩展历史窗口 | `2` |
| `hash_history_hard_limit` | 整数 | 去重历史硬上限，限制数据库体积与监控开销 | `5000` |
| `tracking_query_params` | 列表 | 链接去重时忽略的查询参数（如 utm_source） | 见配置说明 |
| `failed_queue_capacity` | 整数 | 自动失败重试队列容量。`0` 表示禁用自动重试回收，但失败 push history 仍然照常落库保留审计与人工排障信息。 | `50` |
| `failed_queue_max_retries` | 整数 | push history 自动重试上限，只控制失败历史进入自动重试链路的次数，不影响失败历史本身的保留。 | `3` |
| `deduplicate_multi_bot` | 布尔值 | 单会话多 BOT 去重。仅当多个目标落在同一 `target_session`，且最终发送 payload 等价时才压重；被压掉的记录写入 `skipped` push history 作为审计。 | `true` |
| `bootstrap_skip_history` | 布尔值 | 首轮是否跳过历史条目，开启后首次仅建立去重历史不推送旧消息 | `true` |
| `history_entry_limit` | 整数 | 历史条目推送限制，0=不限制 | `0` |
| `download_media_timeout` | 整数 | 媒体下载超时（秒），m3u8/HLS 建议 60-180 秒 | `30` |

### RSSHub Routes 知识库 (`route_knowledge`)

用于将 RSSHub Routes Markdown 文档同步到 AstrBot 知识库。`/rsshub_kb_init` 可按 `kb_name` 自动创建空知识库，也可复用已有知识库；向量模型和重排序模型留空时使用当前第一个可用 Provider。

AstrBot 配置页中，`source_mode`、`source_base_url` 和 `fallback_base_url` 使用下拉选项，避免手动输入不兼容的 raw 镜像格式；有限范围的超时、并发和批量参数使用滑块。当前内置来源包括 GitHub Raw 和 `ghfast.top` raw 代理格式，知识库文件来自公开仓库 `FlanChanXwO/rsshub-routes-knowledgebase`：<https://github.com/FlanChanXwO/rsshub-routes-knowledgebase>。

| 配置项 | 类型 | 说明 | 默认值 |
|--------|------|------|--------|
| `route_knowledge.kb_name` | 字符串 | 同步目标知识库名称 | `RSSHub Routes` |
| `route_knowledge.embedding_provider_id` | 字符串 | 自动创建知识库时使用的向量模型 Provider ID；留空使用第一个可用 Embedding Provider | `""` |
| `route_knowledge.rerank_provider_id` | 字符串 | 自动创建或补齐知识库时使用的重排序模型 Provider ID；留空使用第一个可用 Rerank Provider，无可用 Provider 时关闭重排序 | `""` |
| `route_knowledge.source_mode` | 下拉 | 同步来源模式：`mirror` 使用主地址，`auto` 失败后尝试备用地址，`github` 使用内置 GitHub Raw，`local` 使用本地目录 | `mirror` |
| `route_knowledge.source_base_url` | 下拉 | 包含 `metadata.json`、`index/` 和 `docs/` 的 raw 文件根地址 | GitHub Raw |
| `route_knowledge.fallback_base_url` | 下拉 | `source_mode=auto` 时的备用 raw 文件根地址 | GitHub Raw |
| `route_knowledge.local_source_dir` | 字符串 | `source_mode=local` 时的本地同步目录 | `""` |
| `route_knowledge.timeout` | 滑块整数 | 下载 metadata 和 Markdown 文件的超时时间（秒） | `30` |
| `route_knowledge.batch_size` | 滑块整数 | 传给 AstrBot 知识库上传接口的 batch_size | `32` |
| `route_knowledge.tasks_limit` | 滑块整数 | 传给 AstrBot 知识库上传接口的并发任务数 | `3` |
| `route_knowledge.max_retries` | 滑块整数 | 传给 AstrBot 知识库上传接口的重试次数 | `3` |

### 订阅默认配置（Plugin Pages）

订阅全局默认值不再在 AstrBot 配置页暴露，请在 Plugin Pages 中维护。包括默认监控间隔、通知、发送模式、内容长度、展示策略和媒体展示等。链接预览 `link_preview` 已从 Plugin Pages 控件中移除，不再作为可视化配置项维护。

> 旧配置中的 `global_config` 仍可被运行时读取，避免升级后丢失已有设置。

### 内容处理与 handler

旧版内置翻译、AI enrich 管道已移除；formatter 只负责把已解析条目格式化为平台消息，不再承载内容筛选、翻译或改写职责。基础 HTML/XML 清洗属于内建解析与格式化链；当前 handlers 只负责 `ai_filter` 与 `ai_transform`。外部扩展 handler 先保留为可保存/展示的数据位。

Plugin Pages 的用户/订阅处理链编辑器会优先读取 Web API `handlers/schema`，并在接口尚不可用时使用内置 fallback。当前编辑器支持启停、排序、添加内置 handler、删除、schema 字段编辑和原始 JSON 高级模式，字段类型覆盖 `string`、`text`、`bool`、`int`、`float`、`select`、`list[string]`、`json`。

全局 `content_handlers` 配置可选择内置 AI handler 使用的 AstrBot Provider 和人格。`ai_provider_id` 留空时使用当前会话正在使用的对话模型；`ai_persona_id` 只把人格 system prompt 注入 `ai_filter` / `ai_transform` 的模型调用，不改变用户会话人格，也不在插件里保存 API key。

- `ai_filter` 仍走轻量 provider 判定，配置项为：
  - `prompt`
  - `input_scope=text|raw_xml|both`
  - `reason_max_length`
- `ai_transform` 现在统一走 AstrBot `tool_loop_agent`，配置项为：
  - `prompt`
  - `scope=plaintext|xml`
- `ai_transform(scope=plaintext)` 只允许 agent 返回 `title` / `summary` / `content` JSON 字段。
- `ai_transform(scope=xml)` 让 agent 改写整段 `raw_xml`，并通过内部 XML 校验工具自检；成功后插件会重新解析 XML、重建正文和媒体，再继续正常推送链。
- 无论 `ai_filter` 还是 `ai_transform`，失败默认都不会阻断 RSS 主链；失败信息只会进入 `handler_trace` 便于审计。

### FFmpeg 配置 (`ffmpeg`)

| 配置项 | 类型 | 说明 | 默认值 |
|--------|------|------|--------|
| `ffmpeg.video_transcode` | 布尔值 | 视频发送前自动转码为兼容 H264/AAC MP4 | `false` |
| `ffmpeg.video_transcode_timeout` | 整数 | 视频转码超时时间（秒） | `120` |
| `ffmpeg.gif_transcode` | 布尔值 | 无声视频自动转 GIF | `false` |
| `ffmpeg.gif_transcode_timeout` | 整数 | GIF 转码超时时间（秒） | `60` |

这些配置会在插件启动时写入 sender 运行态。媒体预处理仍复用媒体缓存；无声视频转 GIF 和兼容 MP4 转码由 FFmpeg helper 统一处理，失败时回退原始视频文件，不阻断推送。

### 发送策略配置 (`sender_strategies`)

`sender_strategies.enabled_platforms` 现在是平台多选列表，默认启用 `telegram`、`aiocqhttp`、`qq_official`。未选中的平台会回退到默认发送器。

> 兼容说明：旧版 `sender_strategies.telegram = true` 这类布尔对象配置仍可读取；保存后会写回 `sender_strategies.enabled_platforms`。平台策略统一写入 `sender_strategies.platform_strategies` 这个 `template_list`，可添加 `telegram_strategy` / `onebot_strategy` 等不同模板；当前每类模板只读取第一条。

平台专属 sender 策略模板目前用于 `telegram` 和 `aiocqhttp`。不同模板的配置项不需要一致：

| 配置项 | 类型 | 说明 |
|--------|------|------|
| `enable_telegraph` | 布尔值 | 仅 Telegram 使用：启用 Telegraph 自动分流 |
| `telegraph_token` | 字符串 | 仅 Telegram 使用：Telegraph access token；启用自动分流时必填 |
| `prefer_local_video` | 布尔值 | 仅 OneBot 使用：视频是否优先本地文件；默认关闭，优先远程 URL |

Telegraph 不是显式 `send_mode`。它只会在 Telegram sender 自动策略里触发：当前为自动发送、Telegram 策略已启用 Telegraph、token 有效，且去重后的媒体条目数大于 1。OneBot 不使用 Telegraph，避免在 QQ/NapCat 环境中依赖不可访问的外部页面服务。Telegram 本地图片超过 10 MiB 时会降级为文件发送，避免 Bot API photo 大小限制导致整条推送失败。

发送前会先下载媒体到本地成功缓存，再生成平台无关消息组件并由排序器统一整理顺序；下载失败不会写入失败缓存，下一次推送会重新尝试。OneBot 经典排版按合并转发发送；原始顺序排版会按 RSS/HTML 解析出的布局片段逐条发送，适合 AI 日报这类多图长文。`prefer_local_video` 仅控制 OneBot 视频组件是否优先使用本地文件路径，不再控制是否预下载。

## 📝 使用方法

### 基础命令

所有命令均支持中英文别名，例如 `/sub` 和 `/订阅` 等价：

| 命令                                     | 中文别名 | 说明 |
|----------------------------------------|---------|------|
| `/sub <RSS 链接> [链接2...]`               | `/订阅` | 新增订阅，支持批量订阅多个 RSS 源 |
| `/sub_state <ID> on/off`               | `/订阅状态` | 快速启停订阅推送 |
| `/unsub <ID/URL...>`                   | `/取消订阅` | 取消订阅，支持批量（ID 或 URL） |
| `/unsub_all [global]`                  | `/取消全部订阅` | 删除订阅；默认仅清除当前会话，`global` 清除所有会话（需管理员） |
| `/sub_list [page] [page_size]` | `/订阅列表` | 查看当前会话订阅列表（分页） |
| `/sub_export [all]`                    | `/导出订阅` | 导出订阅到 TOML 文件，默认当前会话，`all`=所有订阅（管理员） |
| `/sub_import [文件路径]`                   | `/导入订阅` | 从 TOML 文件导入订阅；不带参数时进入 5 分钟文件上传等待 |
| `/activate_subs`                       | `/enable_subs`, `/启用全部订阅` | 启用当前会话所有订阅 |
| `/deactivate_subs`                     | `/disable_subs`, `/禁用全部订阅` | 禁用当前会话所有订阅 |
| `/sub_status`                          | `/推送状态`, `/任务状态` | 查看当前会话推送任务（running + queued，含 job_id/feed 信息） |
| `/sub_stop [job_id/feed_id/all]`       | `/停止RSS`, `/停止推送` | 停止推送任务：不带参数停止当前 running 任务；可按 job_id/feed_id 精确停止；`all` 停止当前会话全部任务 |
| `/rsshub_kb_init`                      | - | 管理员初始化 RSSHub Routes 知识库 |
| `/rsshub_kb_sync`                      | - | 管理员启动 RSSHub Routes 知识库同步任务 |
| `/rsshub_kb_status`                    | - | 查看 RSSHub Routes 知识库状态 |
| `/rsshub_kb_task`                      | - | 查看最近一次 Routes KB 同步任务进度 |

**布尔值格式支持**：所有命令中的布尔值参数支持以下格式：`true`/`false`, `yes`/`no`, `y`/`n`, `1`/`0`, `on`/`off`, `enable`/`disable`

### 订阅设置

| 命令 | 中文别名 | 说明 |
|------|---------|------|
| `/sub_profile set sub <订阅 ID> <选项> <值>` | `/订阅配置 设置 sub ...` | 设置订阅级选项 |
| `/sub_profile set user <选项> <值>` | `/订阅配置 设置 user ...` | 设置用户默认选项 |
| `/sub_profile get user [选项]` | `/订阅配置 获取 user ...` | 查看用户配置（无参数显示所有） |
| `/sub_session set [key] [value]` | `/会话设置 设置` | 设置会话级默认项 |
| `/sub_session get [key]` | `/会话设置 获取` | 查看会话默认项（无参数显示所有） |

### 配置继承架构

订阅设置采用三层配置继承体系：

1. **订阅级配置** (`/sub_profile set sub ...`): 字段值为 `-100` 时继承用户级配置，其他值直接作为订阅配置生效
2. **用户级配置** (`/sub_profile set user ...`): 字段值为 `-100` 时继承全局配置，其他值作为用户默认配置生效
3. **全局配置**: AstrBot JSON 配置（默认），新用户开箱即用

`rsshub_sub` 与 `rsshub_user` 不再使用 `use_sub_config` / `use_user_config` 开关列；继承完全由具体配置项的 `-100` 值表达。旧翻译字段也已从这两张表中移除。

**示例**：
```bash
# 让订阅继承用户/全局发送模式
/sub_profile set sub 1 send_mode -100

# 让用户发送模式继承全局配置
/sub_profile set user send_mode -100

# 为订阅设置 AI 过滤 handler
/sub_profile set sub 1 handlers '[{"id":"builtin.ai_filter.default","type":"builtin","name":"ai_filter","status":1,"config":{"prompt":"过滤广告和抽奖内容","input_scope":"both","reason_max_length":120}}]'

# 查看配置来源
/sub_profile get user  # 查看用户配置
/sub_session get       # 查看会话默认
```

### 帮助与测试命令

| 命令 | 中文别名 | 说明 |
|------|---------|------|
| `/rsshelp` | `/RSS 帮助` | 查看帮助图片 |
| `/sub_test <目标>` | `/测试订阅` | 管理员测试推送。目标可以是订阅 ID 或 RSS URL，固定推送最新 1 条 |

> `rsshelp` 使用仓库内预生成并提交的帮助图片：`assets/help/rsshelp.png`。运行时如果图片缺失，只会提示“没有找到帮助图片”，不会自动生成。
>
> 当命令或帮助样式变更后，可手动刷新帮助图：
> ```bash
> python scripts/generate_rsshelp_image.py
> ```

**`/sub_test` 命令示例：**

| 命令 | 说明 |
|------|------|
| `/sub_test 5` | 测试订阅ID=5，推送条目1（最新） |
| `/sub_test https://example.com/rss.xml` | 测试URL，推送最新 1 条 |

> **说明：** 使用URL测试时，将使用全局配置进行推送。

### 订阅选项说明

**订阅级选项（通过 `/sub_profile set sub ...` 设置）：**

| 选项 | 类型 | 说明 |
|------|------|------|
| `state` | 0/1 | 推送状态：0=禁用, 1=启用 |
| `notify` | 0/1 | 是否通知 |
| `send_mode` | -1/0/1 | -1(仅链接)/0(自动)/1(直接发送) |
| `handlers` | JSON 数组 | 内容处理链，支持 `ai_filter` / `ai_transform` |
| `length_limit` | 正整数 | 0 表示不限制 |
| `display_author` | -1~1 | 显示作者 |
| `display_via` | -2~-1/0/1 | 显示来源 |
| `display_title` | -1~1 | 显示标题 |
| `display_entry_tags` | -1~1 | 显示标签 |
| `style` | 0/1/2 | 推送排版策略：0=自动，1=RSSRT，2=原始顺序 |
| `display_media` | -1/0 | 显示媒体 |
| `interval` | 正整数 | 监控间隔（分钟，默认 5） |
| `title` | 字符串 | 订阅标题 |
| `tags` | 字符串 | 标签 |

---

## 🤖 LLM 工具

本插件为 AI 提供以下工具函数：

- `rss_subscribe` - 订阅 RSS 源
- `rss_unsubscribe` - 取消订阅
- `rss_unsubscribe_all` - 取消所有订阅
- `rss_list_subscriptions` - 列出订阅
- `rss_set_subscription_option` - 设置订阅选项
- `rss_set_user_default_option` - 设置用户默认选项
- `rss_set_session_default_option` - 设置会话默认选项
- `rss_get_session_defaults` - 获取会话默认配置
- `rss_list_push_history` - 查询当前会话推送历史（JSON）
- `rss_push_xml_entry` - 解析 XML/HTML 标签内容并推送到当前会话

在 AstrBot 的 LLM 配置中开启工具调用即可使用。

> RSSHub 路由检索后续走 AstrBot 知识库和 route skill；插件不再提供 route 搜索 LLM tool。
>
> 命令仍是新增订阅、导入导出等用户归属流程的兜底入口；Plugin Pages 不提供新增订阅或 TOML 导入导出入口。
>
> `rss_push_xml_entry` 是面向 AI agent 的即时推送工具，不使用订阅 `sub_id`，也不读取订阅默认配置。它会：
> - 对输入 XML 做格式校验，拒绝坏格式、DOCTYPE/ENTITY 和超大输入
> - 将标签内容解析为正文 + 媒体组件
> - 使用 `source_key + user_id + target_session + entry_guid` 做成功态幂等去重
> - 写入推送历史并复用现有失败重试链路
> - 在媒体发送失败时，把原始媒体链接保留到失败历史和回退文本中
> - 为 XML 即时推送历史额外保存 `raw_xml` 以便审计和后续排障

### 基础配置语义补充

- `minimal_interval` 是“保存期硬限制”，不是轮询执行时才生效的软校正。任何写入订阅、用户默认值、会话默认值的入口都不应落库小于该值的监控间隔。
- `failed_queue_capacity=0` 只禁用自动失败重试队列，不会关闭失败历史记录。失败发送仍应写 `push_history`，供审计、展示和人工补发排障。
- `failed_queue_max_retries` 只定义自动重试链路对单条 `push_history` 的最大尝试次数；超过上限后仍保留失败历史，不做静默删除。
- `deduplicate_multi_bot` 只在同一 `target_session` 内比较最终 payload 是否等价；命中后不发送重复消息，但必须保留一条 `status=skipped` 的审计记录。
- 推送历史自动清理范围不属于插件配置页；它只在 Dashboard 的推送历史页管理。Dashboard 也提供清空全部推送历史，用于清理本地测试或旧失败队列爆量数据。

---

## 🏗️ 项目架构 (v2.0.0+)

本项目采用 **领域驱动设计 (DDD)** 分层架构，代码组织清晰、可维护性强。

### 架构分层

```
src/
├── domain/           # 领域层 - 核心业务逻辑
│   ├── entities/     # 领域实体 (Feed, Subscription, User)
│   ├── value_objects/# 值对象 (Entry, Settings)
│   └── repositories/ # 仓库接口定义
├── application/      # 应用层 - 用例编排
│   ├── commands/     # 命令处理 (CQRS)
│   ├── dto/          # 数据传输对象
│   └── services/     # 应用服务
├── infrastructure/   # 基础设施层 - 技术实现
│   ├── config/       # 配置管理
│   ├── messaging/    # 消息发送
│   ├── persistence/  # 数据持久化
│   ├── fetcher/      # RSS 拉取与解析
│   ├── pipeline/     # 消息链格式化
│   ├── schedule/     # 调度服务
│   ├── utils/        # 工具函数
└── __init__.py       # 统一导出
```

### 关键设计原则

1. **依赖倒置**: 领域层不依赖其他层，基础设施层实现领域层定义的接口
2. **命令模式**: 每个业务用例封装为独立的命令类，便于测试和扩展
3. **仓库模式**: 数据访问抽象，支持灵活的存储实现
4. **单例管理**: 关键服务（数据库、配置、调度）采用单例模式
5. **类型安全**: 全面使用 Python 类型注解，增强代码健壮性

---

## 🌐 管理界面

本项目管理界面使用 **AstrBot Plugin Pages**（`pages/dashboard`），通过 AstrBot 面板访问。
后端接口由 `WebApiHandler` 注册到 `/{plugin_name}/...` 路径下（当前为 `/astrbot_plugin_rsshub/...`）。

管理页包含已有订阅管理、用户/Feed 列表、推送历史、默认订阅设置和 RSSHub Routes 知识库同步。WebUI 不创建新订阅，也不提供订阅导入/导出入口；新增、导入和导出订阅请使用聊天命令或 AI agent。用户状态仅保留「用户」和「已封禁」两种；窄屏下订阅表格会切换为卡片式布局，推送历史筛选、分页和知识库状态区域会自动换行，避免按钮或长文本重叠。
订阅列表采用前端分页，分页控件放在列表上方；页面滚动被限制在列表/配置容器内部，避免切换标签页时整页布局抖动。默认订阅设置统一使用底部保存按钮，不再使用遮挡表单的悬浮按钮。

## 🧩 解析与推送兼容性

- RSS 解析优先读取 `content` 结构化正文，并兼容 `content:encoded` / `content_encoded` 字段，适配 Juya AI Daily 等完整正文位于 `content:encoded` 的源。
- HTML `<video>`、`<audio>` 会作为结构化媒体传入发送器，正文中不会残留 `[视频]` / `[音频]` 占位；RSSHub 常见的 `?url=<encoded media>` 包装链接也会参与媒体类型推断。
- 关闭标题显示时，正文不会再因为与标题开头重复而被剔除，适配 bsky 等会把正文首句同步放入标题的源。
- m3u8/HLS 在先下载后发送时会通过 FFmpeg 合并为 MP4，并用 ffprobe 校验视频流与时长；校验失败会按媒体下载失败处理，避免 0 秒坏视频进入缓存。
- OneBot / NapCat 经典合并转发失败后会回退为纯文本 Nodes；多图长文建议使用 `style=2` 的原始顺序排版。
- 推送历史中的失败原因会按 512 字符上限统一截断；旧数据库里遗留的超长失败原因也会在读取时自动清洗，避免 `/push-history` 接口和定时重试任务因脏数据崩溃。

---

## 📄 开源协议

本项目基于 [AGPL](LICENSE) 协议开源。

## 致谢

- [RSS-to-Telegram-Bot：关心你的阅读体验的 Telegram RSS 机器人](https://github.com/Rongronggg9/RSS-to-Telegram-Bot)
- [AstrBot](https://github.com/AstrBotDevs/AstrBot)
- [feedparser](https://github.com/kurtmckee/feedparser)
