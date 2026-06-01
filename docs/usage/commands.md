# 命令说明

所有命令均支持中英文别名，例如 `/sub` 和 `/订阅` 等价。

## 基础命令

| 命令 | 中文别名 | 说明 |
| --- | --- | --- |
| `/sub <RSS 链接> [链接2...]` | `/订阅` | 新增订阅，支持批量订阅多个 RSS 源。 |
| `/sub_state <ID> on/off` | `/订阅状态` | 快速启停订阅推送。 |
| `/unsub <ID/URL...>` | `/取消订阅` | 取消订阅，支持批量传入 ID 或 URL。 |
| `/unsub_all [global]` | `/取消全部订阅` | 删除订阅；默认只清除当前会话，`global` 清除所有会话且需要管理员权限。 |
| `/sub_list [page] [page_size]` | `/订阅列表` | 查看当前会话订阅列表。 |
| `/sub_export [all]` | `/导出订阅` | 导出订阅到 TOML 文件，默认当前会话，`all` 导出所有订阅且需要管理员权限。 |
| `/sub_import [文件路径]` | `/导入订阅` | 从 TOML 文件导入订阅；不带参数时进入 5 分钟文件上传等待。 |
| `/activate_subs` | `/enable_subs`, `/启用全部订阅` | 启用当前会话所有订阅。 |
| `/deactivate_subs` | `/disable_subs`, `/禁用全部订阅` | 禁用当前会话所有订阅。 |
| `/sub_status` | `/推送状态`, `/任务状态` | 查看当前会话推送任务。 |
| `/sub_stop [job_id/feed_id/all]` | `/rss_stop`, `/停止RSS`, `/停止推送` | 停止当前 running 任务、指定任务或当前会话全部任务。 |

布尔值参数支持 `true/false`、`yes/no`、`y/n`、`1/0`、`on/off`、`enable/disable`。

## 订阅设置

| 命令 | 中文别名 | 说明 |
| --- | --- | --- |
| `/sub_profile set sub <订阅 ID> <选项> <值>` | `/订阅配置 设置 sub ...` | 设置订阅级选项。 |
| `/sub_profile set user <选项> <值>` | `/订阅配置 设置 user ...` | 设置用户默认选项。 |
| `/sub_profile get user [选项]` | `/订阅配置 获取 user ...` | 查看用户默认配置。 |
| `/sub_session set [key] [value]` | `/会话设置 设置` | 设置会话级默认项。 |
| `/sub_session get [key]` | `/会话设置 获取` | 查看会话默认项。 |

配置继承顺序为订阅级、用户级、全局配置。订阅级和用户级字段值为 `-100` 时表示继续向上继承。

常用订阅选项：

| 选项 | 类型 | 说明 |
| --- | --- | --- |
| `state` | `0/1` | 推送状态。 |
| `notify` | `0/1` | 是否通知。 |
| `send_mode` | `-1/0/1` | `-1` 仅链接，`0` 自动，`1` 直接发送。 |
| `handlers` | JSON 数组 | 内容处理链，支持 `ai_filter` / `ai_transform`。 |
| `length_limit` | 正整数 | 内容长度限制，`0` 表示不限制。 |
| `display_author` | `-1~1` | 是否显示作者。 |
| `display_via` | `-2~-1/0/1` | 是否显示来源。 |
| `display_title` | `-1~1` | 是否显示标题。 |
| `display_entry_tags` | `-1~1` | 是否显示标签。 |
| `style` | `0/1/2` | 推送排版策略：自动、RSSRT、原始顺序。 |
| `display_media` | `-1/0` | 是否显示媒体。 |
| `interval` | 正整数 | 监控间隔，单位分钟。 |
| `title` | 字符串 | 订阅标题。 |
| `tags` | 字符串 | 标签。 |

示例：

```bash
/sub_profile set sub 1 send_mode -100
/sub_profile set user send_mode -100
/sub_profile get user
/sub_session get
```

## 帮助与测试

| 命令 | 中文别名 | 说明 |
| --- | --- | --- |
| `/rsshelp` | `/RSS帮助`, `/rss帮助` | 查看帮助图片。 |
| `/sub_test <目标>` | `/测试订阅` | 管理员测试推送；目标可以是订阅 ID 或 RSS URL，固定推送最新 1 条。 |
| `/rsshub_kb_init` | `/rss知识库初始化`, `/RSS知识库初始化` | 管理员初始化 RSSHub Routes 知识库。 |
| `/rsshub_kb_sync` | `/rss知识库同步`, `/RSS知识库同步` | 管理员启动 RSSHub Routes 知识库同步任务。 |
| `/rsshub_kb_status` | `/rss知识库同步状态`, `/RSS知识库同步状态` | 查看 RSSHub Routes 知识库状态。 |
| `/rsshub_kb_task` | `/rss知识库近期同步任务`, `/RSS知识库近期同步任务` | 查看最近一次 Routes KB 同步任务进度。 |

`rsshelp` 使用仓库内预生成图片：白天发送 `assets/help/rsshelp_light.png`，夜间发送 `assets/help/rsshelp_dark.png`。命令或帮助样式变化后可手动运行：

```bash
./scripts/gen_rsshelp.sh
```
