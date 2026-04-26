# RSSHub for AstrBot

<div align="center">

<img src="https://raw.githubusercontent.com/FlanChanXwO/astrbot_plugin_rsshub/master/assets/logo.png" width="400" alt="rsshub"/>

<br/>

<img src="https://count.getloli.com/@astrbot_plugin_rsshub?name=astrbot_plugin_rsshub&theme=rule34&padding=7&offset=0&align=top&scale=1&pixelated=1&darkmode=auto" alt="Moe Counter">

**AstrBot RSS 订阅插件。**

[![License: AGPL](https://img.shields.io/badge/License-AGPL-blue.svg)](https://opensource.org/licenses/agpl-3.0)
![Python Version](https://img.shields.io/badge/Python-3.10%2B-blue)
![AstrBot](https://img.shields.io/badge/AstrBot-%E2%89%A54.10.4-green)
![Platform](https://img.shields.io/badge/Platform-Windows%20%7C%20Linux-lightgrey)

</div>

> 新开发者请先阅读贡献指南：[`CONTRIBUTE.md`](./CONTRIBUTE.md)
>
> **⚠️ 本项目正在升级到 v2.0.0，项目结构与数据库 schema 可能发生重大变化，请留意版本更新日志。**

---

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
- 🌐 **WebUI 管理** - 可选 aiohttp WebUI 管理界面，可视化操作订阅
- 📦 **数据导入导出** - 支持 TOML 格式备份和恢复订阅数据
- 🔄 **失败队列** - 平台连接失败时自动进入队列，恢复后重试推送
- 🤝 **多 BOT 支持** - 单会话多 BOT 去重
- 🔍 **RSSHub 集成** - 内置 RSSHub 路由检索，快速构建订阅链接
- 🌐 **自动翻译** - 支持 Google(免费)、百度翻译，自动翻译 RSS 条目内容

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

## 免费 RSS 源实例（公共可用）

> 以下实例为公共服务，稳定性和可用性会随时间变化，建议优先自建或准备备用地址。

| 名称 | 地址 | 类型 | 说明 |
|------|------|------|------|
| RSSHub 官方 | `https://rsshub.app` | RSSHub 实例 | 默认推荐，覆盖路由广 |
| Feedly | `https://feedly.com/i/subscription/feed%2F<URL 编码后的 RSS 链接>` | 在线阅读器 | 免费版可用于管理订阅 |
| Inoreader | `https://www.inoreader.com` | 在线阅读器 | 免费版可聚合多源 |
| Follow | `https://app.follow.is` | 在线阅读器 | 新一代 RSS 聚合器，支持多端 |

> 提示：在本插件中通常将 `rsshub_base_url` 默认设置为可用的 RSSHub 实例地址（如 `https://rsshub.app`）。

---

## 🛠️ 配置项

> **注意**：v2.0.0 版本起，全局配置请前往 AstrBot 管理面板的「配置」页面或 WebUI 进行设置。

在 AstrBot 管理面板的「配置」页面，找到 `RSSHub` 插件配置：

### 基础设施配置 (`basic_config`)

| 配置项 | 类型 | 说明 | 默认值 |
|--------|------|------|--------|
| `proxy` | 字符串 | HTTP/SOCKS 代理地址，留空则不使用代理。例如 `http://127.0.0.1:7890` | `""` |
| `rsshub_base_url` | 字符串 | 默认 RSSHub 域名，用于路由检索与订阅链接拼接 | `https://rsshub.app` |
| `timeout` | 整数 | 请求超时（秒），获取 RSS 源时的 HTTP 请求超时时间 | `30` |
| `minimal_interval` | 整数 | 最小监控间隔（分钟），限制命令/WebUI 设置的最小值 | `1` |
| `hash_history_min` | 整数 | 去重历史最小保留数量，避免历史回流重复推送 | `500` |
| `hash_history_multiplier` | 整数 | 去重历史增长倍数，动态扩展历史窗口 | `2` |
| `hash_history_hard_limit` | 整数 | 去重历史硬上限，限制数据库体积与监控开销 | `5000` |
| `tracking_query_params` | 列表 | 链接去重时忽略的查询参数（如 utm_source） | 见配置说明 |
| `failed_queue_capacity` | 整数 | 失败队列容量，0=禁用失败队列 | `50` |
| `failed_queue_max_retries` | 整数 | 失败队列最大重试次数 | `3` |
| `deduplicate_multi_bot` | 布尔值 | 单会话多 BOT 去重，避免重复推送 | `true` |
| `bootstrap_skip_history` | 布尔值 | 首轮是否跳过历史条目，开启后首次仅建立去重历史不推送旧消息 | `true` |
| `debug_payload` | 布尔值 | 调试模式，在消息末尾显示条目详细信息 | `false` |
| `history_entry_limit` | 整数 | 历史条目推送限制，0=不限制 | `0` |
| `download_media_before_send` | 布尔值 | 先下载媒体后发送，Docker 环境下需共享数据卷 | `false` |
| `download_media_timeout` | 整数 | 媒体下载超时（秒），m3u8/HLS 建议 60-180 秒 | `30` |

### 订阅全局默认配置 (`global_config`)

| 配置项 | 类型 | 说明 | 默认值 |
|--------|------|------|--------|
| `interval` | 整数 | 默认监控间隔（分钟），订阅未设置 interval 时使用 | `5` |
| `notify` | 布尔值 | 是否发送 RSS 更新通知 | `true` |
| `send_mode` | 字符串 | 发送模式：仅链接/自动/直接消息 | `自动` |
| `length_limit` | 整数 | 内容长度限制，0=不限制 | `0` |
| `link_preview` | 字符串 | 链接预览：自动/强制启用 | `自动` |
| `display_author` | 字符串 | 显示作者：禁用/自动/强制 | `自动` |
| `display_via` | 字符串 | 显示来源：完全禁用/仅链接/自动/强制 | `自动` |
| `display_title` | 字符串 | 显示标题：禁用/自动/强制 | `自动` |
| `display_entry_tags` | 布尔值 | 是否在推送中显示 RSS 条目标签 | `false` |
| `style` | 字符串 | 推送样式：RSStT/flowerss | `RSStT` |
| `display_media` | 布尔值 | 是否在推送中显示图片、视频等媒体 | `true` |
| `translate` | 布尔值 | 是否自动翻译 RSS 内容 | `false` |
| `translate_target_lang` | 字符串 | 翻译目标语言：zh-CN/zh-TW/en/ja | `zh-CN` |

### FFmpeg 配置 (`ffmpeg`)

| 配置项 | 类型 | 说明 | 默认值 |
|--------|------|------|--------|
| `ffmpeg.video_transcode` | 布尔值 | 视频发送前自动转码为兼容 H264/AAC MP4 | `false` |
| `ffmpeg.video_transcode_timeout` | 整数 | 视频转码超时时间（秒） | `120` |
| `ffmpeg.gif_transcode` | 布尔值 | 无声视频自动转 GIF | `true` |
| `ffmpeg.gif_transcode_timeout` | 整数 | GIF 转码超时时间（秒） | `60` |

### 发送策略配置 (`sender_strategies`)

| 配置项 | 类型 | 说明 | 默认值 |
|--------|------|------|--------|
| `sender_strategies.telegram` | 布尔值 | 启用 Telegram 专用策略（媒体优先、大小限制处理） | `true` |
| `sender_strategies.aiocqhttp` | 布尔值 | 启用 OneBot 专用策略（合并转发节点） | `true` |
| `sender_strategies.weixin_oc` | 布尔值 | 启用微信个人号专用策略 | `true` |

> **命名说明：**
> - 配置文件中使用 `sender_strategies.<platform>` 形式（点号分隔），例如：`sender_strategies.telegram`、`sender_strategies.aiocqhttp`
> - `/rss_conf` 命令参数中使用 `sender_strategy_<platform>` 形式（下划线分隔），例如：`sender_strategy_telegram`、`sender_strategy_aiocqhttp`
> - 两者是一一对应的配置项，仅书写形式不同，含义完全相同

### 翻译配置 (`translation`)

| 配置项 | 类型 | 说明 | 默认值 |
|--------|------|------|--------|
| `translation.provider` | 字符串 | 翻译服务提供商：`google`(免费) / `baidu` | `google` |
| `translation.target_lang` | 字符串 | 目标语言：`zh-CN`, `zh-TW`, `en`, `ja` | `zh-CN` |
| `translation.auto_translate` | 布尔值 | 是否自动翻译新条目 | `false` |
| `translation.force_translate` | 布尔值 | 是否跳过语言检测强制翻译 | `false` |
| `translation.translate_title` | 布尔值 | 是否翻译标题 | `true` |
| `translation.translate_content` | 布尔值 | 是否翻译正文 | `true` |
| `translation.display_orignal_content` | 布尔值 | 是否显示原文（格式：原文 + 换行 + 分隔线 + 译文） | `false` |
| `translation.cache_translations` | 布尔值 | 是否缓存翻译结果以减少 API 调用 | `true` |

**百度翻译认证配置** (`translation_template`)：

| 配置项 | 类型 | 说明 |
|--------|------|------|
| `translation_template.baidu.baidu_appid` | 字符串 | 百度翻译 AppID（申请地址：http://api.fanyi.baidu.com） |
| `translation_template.baidu.baidu_key` | 字符串 | 百度翻译 API 密钥 |

**使用说明：**
- Google 翻译无需配置，开箱即用（免费但有频率限制）
- 百度翻译需要申请 AppID 和密钥
- 翻译功能可全局开启或按订阅单独控制
- 按订阅控制：`/sub_set <订阅 ID> translate=1` 开启、`translate=0` 关闭

### WebUI 配置 (`webui`)

| 配置项 | 类型 | 说明 | 默认值 |
|--------|------|------|--------|
| `webui.enabled` | 布尔值 | 启用 WebUI 管理界面 | `false` |
| `webui.host` | 字符串 | 监听地址，`0.0.0.0`=允许外部访问 | `0.0.0.0` |
| `webui.port` | 整数 | 监听端口 | `9191` |
| `webui.auth_enabled` | 布尔值 | 启用登录验证 | `true` |
| `webui.password` | 字符串 | 访问密码，留空则自动生成 6 位随机密码 | `""` |
| `webui.session_timeout` | 整数 | 会话超时时间（秒） | `3600` |

---

## 📝 使用方法

### 基础命令

所有命令均支持中英文别名，例如 `/sub` 和 `/订阅` 等价：

| 命令                                     | 中文别名 | 说明 |
|----------------------------------------|---------|------|
| `/sub <RSS 链接> [链接2...]`               | `/订阅` | 新增订阅，支持批量订阅多个 RSS 源 |
| `/sub_state <ID> on/off`               | `/订阅状态` | 快速启停订阅推送 |
| `/unsub <ID/URL...>`                   | `/取消订阅` | 取消订阅，支持批量（ID 或 URL） |
| `/unsub_all [global]`                  | `/取消全部订阅` | 删除订阅；默认仅清除当前会话，`global` 清除所有会话（需管理员） |
| `/sub_list [scope] [page] [page_size]` | `/订阅列表` | 查看当前用户订阅列表（管理员可用 `all` 查看所有会话） |
| `/sub_export [all]`                    | `/导出订阅` | 导出订阅到 TOML 文件，默认当前会话，`all`=所有订阅（管理员） |
| `/sub_import [文件路径]`                   | `/导入订阅` | 从 TOML 文件导入订阅；也可直接上传 TOML 文件进行导入 |
| `/activate_subs`                       | `/enable_subs`, `/启用全部订阅` | 启用当前会话所有订阅 |
| `/deactivate_subs`                     | `/disable_subs`, `/禁用全部订阅` | 禁用当前会话所有订阅 |

**布尔值格式支持**：所有命令中的布尔值参数支持以下格式：`true`/`false`, `yes`/`no`, `y`/`n`, `1`/`0`, `on`/`off`, `enable`/`disable`

### 订阅设置

| 命令 | 中文别名 | 说明 |
|------|---------|------|
| `/sub_set <订阅 ID> <选项> <值>` | `/设置订阅` | 设置订阅选项 |
| `/sub_set_user [选项] [值]` | `/设置用户` | 设置用户默认选项（无参数显示帮助） |
| `/sub_get_user [选项]` | `/获取用户` | 查看用户配置（无参数显示所有） |
| `/sub_set_session [key] [value]` | `/设置会话` | 设置会话级默认项（无参数显示帮助） |
| `/sub_get_session [key]` | `/获取会话` | 查看会话默认项（无参数显示所有） |

### 配置继承架构

v1.1.0 起引入三层配置继承体系：

1. **订阅级配置** (`/sub_set`): 通过 `use_sub_config` 控制
   - `true`: 使用 `/sub_set` 设置的独立配置
   - `false` (默认): 继承用户级配置

2. **用户级配置** (`/sub_set_user`): 通过 `use_user_config` 控制
   - `true`: 使用 `/sub_set_user` 设置的用户配置
   - `false` (默认): 继承全局配置

3. **全局配置**: AstrBot JSON 配置（默认）
   - 新用户开箱即用，无需额外配置

**示例**：
```bash
# 让订阅使用独立配置
/sub_set 1 use_sub_config true

# 让用户使用独立配置
/sub_set_user use_user_config true

# 查看配置来源
/sub_get_user          # 查看用户配置
/sub_get_session       # 查看会话默认
```

### 管理命令

| 命令 | 中文别名 | 说明 |
|------|---------|------|
| `/sub_test <目标> [起始] [结束]` | `/测试订阅` | 管理员测试推送。目标可以是订阅 ID 或 RSS URL；条目编号从 1 开始（1=最新） |
| `/rsshelp` | `/RSS 帮助` | 查看帮助 |
| `/rsshelp` | `/RSS 帮助` | 查看帮助 |

**`/sub_test` 命令示例：**

| 命令 | 说明 |
|------|------|
| `/sub_test 5` | 测试订阅ID=5，推送条目1（最新） |
| `/sub_test 5 1 3` | 测试订阅ID=5，推送条目1、2、3 |
| `/sub_test https://example.com/rss.xml 2` | 测试URL，只推送条目2 |
| `/sub_test https://example.com/rss.xml 1 5` | 测试URL，推送条目1-5 |

> **说明：** 使用URL测试时，将使用全局配置进行推送。

### 订阅选项说明

**订阅级选项（通过 `/sub_set` 设置）：**

| 选项 | 类型 | 说明 |
|------|------|------|
| `use_sub_config` | bool | 是否使用订阅独立配置（默认 false） |
| `state` | 0/1 | 推送状态：0=禁用, 1=启用 |
| `notify` | 0/1 | 是否通知 |
| `send_mode` | -1/0/2 | -1(仅链接)/0(自动)/2(直接消息) |
| `length_limit` | 正整数 | 0 表示不限制 |
| `link_preview` | 0/1 | 链接预览 |
| `display_author` | -1~1 | 显示作者 |
| `display_via` | -2~-1/0/1 | 显示来源 |
| `display_title` | -1~1 | 显示标题 |
| `display_entry_tags` | -1~1 | 显示标签 |
| `style` | 0/1 | 样式 (RSStT/flowerss) |
| `display_media` | -1/0 | 显示媒体 |
| `interval` | 正整数 | 监控间隔（分钟，默认 5） |
| `title` | 字符串 | 订阅标题 |
| `tags` | 字符串 | 标签 |
| `translate` | 0/1 | 翻译开关 |
| `translate_target_lang` | 字符串 | 翻译目标语言 |

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
- `rsshub_search_routes` - 搜索 RSSHub 路由
- `rsshub_get_route_schema` - 获取 RSSHub 路由参数
- `rsshub_build_subscribe_url` - 构建 RSSHub 订阅链接

在 AstrBot 的 LLM 配置中开启工具调用即可使用。

---

## 🌐 WebUI

在插件配置 `webui.enabled=true` 后自动启动

- 默认地址：`http://0.0.0.0:9191`
- 主要接口：
    - `GET /` 页面
    - `POST /api/login` 登录
    - `GET /api/subscriptions` 获取订阅列表
    - `PATCH /api/subscriptions/{sub_id}` 更新订阅
    - `DELETE /api/subscriptions/{sub_id}` 删除订阅

---

## 📄 开源协议

本项目基于 [AGPL](LICENSE) 协议开源。
