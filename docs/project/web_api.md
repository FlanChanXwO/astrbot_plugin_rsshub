# Web API 与 Dashboard 数据面

## 负责什么

`src/interfaces/web_api.py` 是 Plugin Pages 的 HTTP 数据面，它不直接承载业务规则，而是把应用层命令、查询和仓储结果变成前端可以消费的 JSON。

## 为什么要单独写 Web API 层

这个插件的前端不是静态展示，而是高频操作面：

- 订阅、用户、Feed、推送历史都要查、改、删
- 测试推送、刷新、清理缓存、清理历史都要触发写操作
- Routes KB 同步需要看任务状态

如果让前端直接拼业务对象，会把数据库结构和 UI 耦合死；如果把逻辑塞进页面，也会让每个按钮都重复写一遍规则。所以 Web API 的职责是：**统一把应用层用例暴露给 Dashboard**。

## 端点分组

当前 Web API 可以按功能分成几组：

1. 订阅 / 用户 / Feed 列表
2. 订阅编辑与批量操作
3. 测试推送
4. 推送历史与清理
5. 数据管理（cache / exports）
6. Routes KB 状态与同步
7. 插件设置与 handler schema

## 订阅列表接口

### `GET /subscriptions`

支持的过滤字段：

- `user_id`
- `feed_id`
- `sub_id`
- `keyword`

调用路径是：

1. 解析多值过滤参数
2. 交给 `SubscriptionRepository.list_for_dashboard()`
3. 再补 Feed 信息
4. 返回前端列表对象

### 过滤规则

- `sub_id` 精确匹配
- `user_id` 精确匹配
- `feed_id` 精确匹配
- `keyword` 会在以下字段上模糊匹配：
  - 订阅标题
  - 订阅标签
  - 用户 ID
  - Feed 标题
  - Feed 链接

这意味着前端不需要先拉全量数据再本地过滤，服务端就能完成主筛选。

## 用户与 Feed 列表

### `GET /users`

这个接口更偏统计视图，按 `user_id` 汇总：

- 总订阅数
- 启用订阅数

### `GET /users/detail`

这个接口返回用户实体细节，可按：

- `user_id`
- `keyword`

过滤，适合前端“点用户行 -> 跳订阅列表”的联动。

### `GET /feeds`

按 `feed_id`、`keyword` 过滤，返回 Feed 的基础信息和订阅数。

## 测试推送接口

### `POST /test-subscription`

当前语义是“真实链路单条模拟发送”，不是预览。

流程：

1. 校验 `sub_id`
2. 读取订阅
3. 补齐 `target_session` 和 `platform_name`
4. 调用 `TestSubscriptionCommand.execute_target()`
5. 走真实 dispatcher 链路

### `POST /test-url`

这是 URL 直发路径：

- 不读取订阅
- 不应用订阅默认配置
- 只把 URL 当作临时测试目标

## 推送历史接口

### `GET /push-history`

返回字段包括：

- `content`
- `raw_xml`
- `media_urls`
- `handler_trace`
- `fail_reason`
- `source_type`
- `source_key`
- `entry_title`
- `entry_link`
- `entry_guid`
- `feed_title`
- `feed_link`
- `sub_id`

支持：

- `status`
- `user_id`
- `target_session`
- `keyword`
- 分页

### `POST /push-history/cleanup`

按保留天数清理推送历史。清理判断使用记录的最后活动时间，也就是 `created_at`、`updated_at`、`completed_at` 中较新的时间，避免仍在近期更新的失败记录被误删。响应会返回 `removed_count`。

### `POST /push-history/clear`

清空全部推送历史，用于本地测试或旧失败队列爆量后快速止血。这个接口只删除 push history，不删除订阅、Feed 或用户配置。

## 数据管理接口

### `GET /data-management/overview`

统计两个目录：

- cache
- exports

返回：

- 文件数
- 总大小
- 分类 breakdown

### 导出文件相关

- `GET /data-management/exports`
- `GET /data-management/exports/content`
- `GET /data-management/exports/download`
- `POST /data-management/exports/delete`
- `POST /data-management/exports/clear`

这些接口只管理插件自己的导出目录，不做通用文件管理。

## Routes KB 接口

- `GET /route-kb/status`
- `POST /route-kb/sync`
- `GET /route-kb/task`

它们只是把 `RouteKnowledgeSyncService` 的状态与任务暴露给前端。

## 插件设置接口

- `GET /plugin-settings`
- `POST /plugin-settings`

它们只处理启动级和默认订阅级配置，不承担订阅创建、导入导出这类用户归属流程。

推送历史自动清理范围不再通过 `plugin-settings` 暴露或保存；它属于推送历史页自己的业务设置。

这里有几条必须对齐后端真实语义的配置约束：

- `minimal_interval` 是写入期硬限制；前端和 API 不应接受并保存更小的监控间隔
- `failed_queue_capacity=0` 只表示关闭自动失败重试，不表示关闭失败历史
- `failed_queue_max_retries` 只定义自动重试上限
- `deduplicate_multi_bot` 只在同一 `target_session` 且最终 payload 等价时生效；命中后应能在 push history 中看到 `skipped` 审计结果

## 设计理由

Web API 的关键不是“返回更多字段”，而是把前端交互统一成一套服务端语义：

- 联动筛选走统一后端过滤
- 详情、编辑、清理、测试都走命令/仓储
- 前端只负责发请求和渲染
