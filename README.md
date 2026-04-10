# RSSHub for AstrBot

<div align="center">

<br/>

**AstrBot RSS 订阅插件。**

[![License: AGPL](https://img.shields.io/badge/License-AGPL-blue.svg)](https://opensource.org/licenses/agpl-3.0)
![Python Version](https://img.shields.io/badge/Python-3.10%2B-blue)
![AstrBot](https://img.shields.io/badge/AstrBot-%E2%89%A54.10.4-green)
![Platform](https://img.shields.io/badge/Platform-Windows%20%7C%20Linux-lightgrey)

</div>

> 新开发者请先阅读贡献指南：[`CONTRIBUTE.md`](./CONTRIBUTE.md)

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

- 📡 **RSS/Atom 订阅** - 支持订阅各类 RSS/Atom 源，实时推送更新
- 🔔 **智能推送** - 按订阅级/会话级 interval 调度，同一 feed 在不同会话可使用不同检查间隔
- 🎨 **富媒体支持** - 基于 HTML 结构解析内容（链接、图片、音频、视频、文件、At 组件等）
- ⚙️ **灵活配置** - 订阅级与用户默认级的消息格式选项，会话级默认配置（KV）
- 🤖 **LLM 工具调用** - 支持 AI 订阅、查询、管理等操作（除 `sub_test` 外）
- 🌐 **WebUI 管理** - 可选 aiohttp WebUI 管理界面，可视化操作订阅
- 📦 **数据导入导出** - 支持 TOML 格式备份和恢复订阅数据
- 🔄 **失败队列** - 平台连接失败时自动进入队列，恢复后重试推送
- 🤝 **多 BOT 支持** - 单会话多 BOT 去重，平台级订阅共享
- 🔍 **RSSHub 集成** - 内置 RSSHub 路由检索，快速构建订阅链接

---

## 📦 安装

### 方式一：通过 AstrBot 插件市场安装（推荐）

在 AstrBot 管理面板中搜索 `RSSHub` 并安装。

### 方式二：手动安装

1. 克隆本仓库到 AstrBot 的插件目录：
   ```bash
   cd AstrBot/data/plugins
   git clone https://github.com/your-repo/astrbot_plugin_rsshub.git
   ```

2. 重启 AstrBot 或重载插件

---

## 🛠️ 配置项

在 AstrBot 管理面板的「配置」页面，找到 `RSSHub` 插件配置：

### 网络配置

| 配置项               | 类型  | 说明                                                  | 默认值                  |
|-------------------|-----|-----------------------------------------------------|----------------------|
| `proxy`           | 字符串 | HTTP/SOCKS 代理地址，留空则不使用代理。例如 `http://127.0.0.1:7890` | `""`                 |
| `rsshub_base_url` | 字符串 | 默认 RSSHub 域名，用于路由检索与订阅链接拼接                          | `https://rsshub.app` |
| `timeout`         | 整数  | 请求超时（秒），获取 RSS 源时的 HTTP 请求超时时间                      | `30`                 |

### 监控配置

| 配置项                | 类型 | 说明                            | 默认值  |
|--------------------|----|-------------------------------|------|
| `default_interval` | 整数 | 默认监控间隔（分钟），订阅未设置 interval 时使用 | `10` |
| `minimal_interval` | 整数 | 最小监控间隔（分钟），限制命令/WebUI 设置的最小值  | `1`  |

### 去重配置

| 配置项                       | 类型 | 说明                         | 默认值    |
|---------------------------|----|----------------------------|--------|
| `hash_history_min`        | 整数 | 去重历史最小保留数量，避免历史回流重复推送      | `200`  |
| `hash_history_multiplier` | 整数 | 去重历史增长倍数，动态扩展历史窗口          | `2`    |
| `hash_history_hard_limit` | 整数 | 去重历史硬上限，限制数据库体积与监控开销       | `5000` |
| `tracking_query_params`   | 列表 | 链接去重时忽略的查询参数（如 utm_source） | 见配置说明  |

### 发送配置

| 配置项                          | 类型  | 说明                        | 默认值     |
|------------------------------|-----|---------------------------|---------|
| `download_image_before_send` | 布尔值 | 先下载图片再发送，docker 环境下需共享数据卷 | `false` |
| `failed_queue_capacity`      | 整数  | 失败队列容量，0=禁用失败队列           | `50`    |

### 发送策略配置 (`sender_strategies`)

| 配置项                           | 类型  | 说明                            | 默认值    |
|-------------------------------|-----|-------------------------------|--------|
| `sender_strategies.telegram`  | 布尔值 | 启用 Telegram 专用策略（媒体优先、大小限制处理） | `true` |
| `sender_strategies.aiocqhttp` | 布尔值 | 启用 OneBot 专用策略（合并转发节点）        | `true` |

### 多 BOT 配置

| 配置项                              | 类型  | 说明                 | 默认值     |
|----------------------------------|-----|--------------------|---------|
| `deduplicate_multi_bot`          | 布尔值 | 单会话多 BOT 去重，避免重复推送 | `true`  |
| `platform_shared_data.aiocqhttp` | 布尔值 | aiocqhttp 平台共享数据源  | `false` |

**说明：**

- **单会话多 BOT 去重**：开启后，当同一会话中有多个 BOT 订阅了相同的 RSS 源，只有最早订阅的 BOT 会推送消息
- **平台共享数据源**：开启后，该平台下所有 BOT 的订阅数据共享，任意 BOT 掉线时其他 BOT 可继续推送

### WebUI 配置 (`webui`)

| 配置项                     | 类型  | 说明                    | 默认值       |
|-------------------------|-----|-----------------------|-----------|
| `webui.enabled`         | 布尔值 | 启用 WebUI 管理界面         | `false`   |
| `webui.host`            | 字符串 | 监听地址，`0.0.0.0`=允许外部访问 | `0.0.0.0` |
| `webui.port`            | 整数  | 监听端口                  | `9191`    |
| `webui.auth_enabled`    | 布尔值 | 启用登录验证                | `true`    |
| `webui.password`        | 字符串 | 访问密码，留空则自动生成 6 位随机密码  | `""`      |
| `webui.session_timeout` | 整数  | 会话超时时间（秒）             | `3600`    |

---

## 📝 使用方法

### 基础命令

| 命令                                   | 说明                                               |
|--------------------------------------|--------------------------------------------------|
| `/sub <RSS链接> [目标]`                  | 新增订阅，目标可选 `private`/`group`/`current`/完整 session |
| `/unsub <订阅ID>`                      | 删除单个订阅                                           |
| `/unsub_all [global]`                | 删除订阅；默认仅清除当前会话，`global` 清除所有会话（需管理员）             |
| `/sub_list [all [page] [page_size]]` | 查看当前用户订阅列表（管理员可用 `all` 查看所有会话）                   |
| `/sub_export [all]`                  | 导出订阅到 TOML 文件，默认当前会话，`all`=所有订阅（管理员）             |
| `/sub_import [文件路径]`                 | 从 TOML 文件导入订阅                                    |

### 订阅设置

| 命令                                       | 说明                            |
|------------------------------------------|-------------------------------|
| `/sub_set <订阅ID> <选项> <值>`               | 设置单个订阅选项（支持 `target_session`） |
| `/sub_set_default <选项> <值>`              | 设置用户默认选项                      |
| `/sub_bind <目标>`                         | 绑定当前用户默认推送目标                  |
| `/sub_session_default_set <key> <value>` | 设置会话级订阅默认项（新订阅自动继承）           |
| `/sub_session_default_get`               | 查看当前会话默认项                     |

### 插件配置

| 命令                        | 说明       |
|---------------------------|----------|
| `/rss_conf`               | 查看当前插件配置 |
| `/rss_conf <key>`         | 查看指定配置项  |
| `/rss_conf <key> <value>` | 设置指定配置项  |

**可配置项：** `proxy`/`rsshub_base_url`/`default_interval`/`minimal_interval`/`timeout`/`download_image_before_send`/
`failed_queue_capacity`/`sender_strategy_telegram`/`sender_strategy_aiocqhttp`/`deduplicate_multi_bot`/
`platform_shared_data_aiocqhttp`

### 管理命令

| 命令                      | 说明                                     |
|-------------------------|----------------------------------------|
| `/sub_test <订阅ID> [粒度]` | 管理员手动触发测试推送，粒度可选 `latest`/`all`/`<数量>` |
| `/sub_failed_queue`     | 查看失败队列状态                               |
| `/rsshelp`              | 查看帮助                                   |

### 订阅选项说明

**订阅级选项：**

- `notify`: 0/1 - 是否通知
- `send_mode`: -1(仅链接)/0(自动)/2(直接消息)
- `length_limit`: 正整数，0表示不限制
- `link_preview`: 0/1 - 链接预览
- `display_author`: -1~1 - 显示作者
- `display_via`: -2~-1/0/1 - 显示来源
- `display_title`: -1~1 - 显示标题
- `display_entry_tags`: -1~1 - 显示标签
- `style`: 0/1 - 样式 (RSStT/flowerss)
- `display_media`: -1/0 - 显示媒体
- `interval`: 正整数 - 监控间隔（分钟）
- `title`: 字符串 - 订阅标题
- `tags`: 字符串 - 标签
- `target_session`: 字符串 - 推送目标会话

---

## 🤖 LLM 工具

本插件为 AI 提供以下工具函数：

- `rss_subscribe` - 订阅 RSS 源
- `rss_unsubscribe` - 取消订阅
- `rss_unsubscribe_all` - 取消所有订阅
- `rss_list_subscriptions` - 列出订阅
- `rss_set_subscription_option` - 设置订阅选项
- `rss_set_user_default_option` - 设置用户默认选项
- `rss_bind_default_target` - 绑定默认推送目标
- `rss_get_plugin_config` - 获取插件配置
- `rss_set_plugin_config` - 设置插件配置
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
