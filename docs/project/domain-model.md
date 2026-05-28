# 领域值、枚举与常量归属

本文是跨模块稳定值的唯一细节来源。修改实体、DTO、配置模型、sender strategy、数据库迁移或共享常量时优先参考本文。

> [!IMPORTANT]
> 这里记录的是跨层契约。某个函数内部的实现细节、局部阈值、缓存 GC 节奏，不应为了“统一”硬塞进共享常量。

## 核心领域值速查

| 领域值 | 当前取值 | 语义 | 备注 |
| --- | --- | --- | --- |
| 配置继承标记 | `-100` | 订阅继承用户配置，用户继承全局默认 | 不恢复 `use_sub_config` / `use_user_config`。 |
| 用户状态 | `1` / `-1` | `USER_STATE_USER` / `USER_STATE_BANNED` | 旧非负状态统一视为普通用户。 |
| `send_mode` | `-1` / `0` / `1` | 仅链接 / 自动 / 直接发送 | 旧 `1=Telegraph` 归一化为 `0`，旧 `2=直接消息` 归一化为 `1`。 |
| `style` | `0` / `1` / `2` | 自动或平台经典 / RSSRT / original | 旧 `flowerss=1` 迁移为 `0`，不恢复 flowerss UI 文案。 |
| 显示类字段 | 整数状态 | `display_author`、`display_via`、`display_title`、`display_entry_tags`、`display_media` | 需要支持继承，不能简化为 `true/false`。 |
| `source_type` | `feed` / `agent` | 普通订阅轮询或测试推送 / AI tool 或 XML 即时推送 | `source_key` 必须稳定表达去重范围。 |
| `handlers_mode` | disabled / override / inherit 等 | 订阅级 handler 链继承策略 | 只属于订阅配置。 |

配置继承关系：

```text
subscription option
  -> user option
  -> global default
```

## 数据模型约束

| 对象 | 必须保持的语义 | 不要恢复 |
| --- | --- | --- |
| `rsshub_sub` | 订阅配置通过 `-100` 继承用户配置；`handlers` 保存 JSON handler 链 | `use_sub_config`、旧翻译列语义、`ai_prompt`。 |
| `rsshub_user` | 用户配置通过 `-100` 继承全局默认；`handlers` 保存 JSON handler 链 | `use_user_config`、插件自有 admin / guest 角色。 |
| `rsshub_user` 事实表 | 订阅或推送历史中出现的非空 `user_id` 都应有对应用户行 | 不要让订阅 / 历史长期引用缺失用户。 |
| `push_history` | 保存最终可发送文本、原始 XML、媒体上下文、失败原因和 handler trace | 不要把失败历史当成可随意丢弃的临时日志。 |

启动期数据库自愈会从订阅和推送历史补齐缺失用户。删除用户默认删除该用户订阅，但推送历史默认保留，只有显式选择时才删除。

## Handler 配置

| 字段 / 概念 | 当前语义 | 备注 |
| --- | --- | --- |
| `rsshub_sub.handlers` | 订阅级 JSON handler 链 | 可覆盖或禁用用户级处理器。 |
| `rsshub_user.handlers` | 用户级 JSON handler 链 | 作为订阅继承来源。 |
| `handlers_mode` | 订阅级继承、覆盖或禁用策略 | 用户配置不需要该字段。 |
| 内置 handler | `ai_filter`、`ai_transform` | HTML/XML 基础清洗属于解析与格式化链，不是可配置 handler。 |
| legacy prompt | 旧非空 `ai_prompt` 迁移为 `builtin.ai_transform` | 不恢复独立 `ai_prompt` 字段。 |

## 推送历史状态与来源

| 状态 / 来源 | 语义 | 备注 |
| --- | --- | --- |
| `success` | 成功发送，参与成功态去重 | 只对成功态做幂等去重。 |
| `failed` | 发送失败，保留失败原因和媒体上下文 | 可用于人工重试和排障。 |
| `skipped` | handler 或多 bot 等价去重压制 | 必须保留审计记录。 |
| `stopped` | 任务被停止 | 不进入自动重试。 |
| `source_type=feed` | 正常订阅轮询或测试推送 | `source_key` 应包含稳定 feed/sub 范围。 |
| `source_type=agent` | AI tool / XML 即时推送 | 不依赖公开 `sub_id`。 |

## 配置模型归属

| 文件 | 职责 |
| --- | --- |
| `src/infrastructure/config/models/plugin_config_models.py` | AstrBot 持久化配置模型。 |
| `src/infrastructure/config/models/runtime_settings.py` | 运行态设置。 |
| `src/infrastructure/config/models/sender_strategy_models.py` | sender strategy 兼容模型。 |
| `src/infrastructure/config/datamodels.py` | 兼容 re-export，不放新模型。 |

## 常量归属

| 放置位置 | 适合内容 | 不适合内容 |
| --- | --- | --- |
| `src/shared/constants.py` | 跨 domain / application / infrastructure 共同使用的领域值；平台限制或可能随平台调整的默认策略；sender strategy 公共枚举候选；用户状态、继承值、发送模式、排版策略等稳定语义 | 单个函数内部实现细节；缓存 GC 间隔；媒体完整性最小字节数；只在单个模块内部使用且不会形成跨层契约的局部值。 |
| 具体实现或运行时设置附近 | 固定实现细节、局部运行参数、单模块私有值 | 会被多层依赖或形成持久化 / API 语义的值。 |

## 配置面边界

| 配置面 | 暴露内容 | 不属于这里 |
| --- | --- | --- |
| `_conf_schema.json` | HTTP 网络配置、Routes KB provider/source、content handler AI provider/persona、credentials、平台 sender strategy | 订阅默认值、用户/订阅继承选项、推送历史页业务设置。 |
| Plugin Pages | 订阅默认值、用户配置、订阅配置、处理器链、推送历史清理设置 | 启动级 provider/source/credentials 的底层 schema 定义。 |
| 配置自愈测试 | `_conf_schema.json` 字段新增、删除、类型变化时必须同步 | 不要只改 schema 而不更新自愈回归。 |

固定选择字段使用 `options`；有上下界的数字字段使用 `slider`。
