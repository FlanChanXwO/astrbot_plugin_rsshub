# 仓储与数据模型

## 负责什么

仓储层负责把领域实体和 SQLite ORM 之间互相转换。

当前核心仓储有：

- `FeedRepositoryImpl`
- `SubscriptionRepositoryImpl`
- `UserRepositoryImpl`
- `PushHistoryRepositoryImpl`

## 为什么仓储要单独写

插件的运行态有很多“看起来像业务，实际上是存储细节”的事情：

- handlers 要以 JSON 存储，但运行时要展开成链
- `push_history` 既是日志，也是重试和审计的数据源
- Dashboard 需要组合过滤，但领域对象不应该直接知道 SQL 条件

仓储层的作用就是把这些细节吞下去，让应用层只看到稳定实体。

## Feed 仓储

### `get_or_create(link, title)`

按 `link` 查找，不存在就创建。

原因：

- Feed 的自然主键在实际语义上就是链接
- 订阅创建时需要幂等

### `save(feed)`

如果 `feed.id` 已存在，更新现有行；否则插入新行。

这避免了重复主键插入。

### `delete_many(feed_ids)`

删除一批 Feed。这个方法只负责 Feed 表自身删除；Dashboard 删除 Feed 的级联订阅和可选推送历史清理由 Web API 编排对应仓储完成。

## Subscription 仓储

### `list_for_dashboard(...)`

这是 Dashboard 的核心查询：

- 支持 `user_ids`
- 支持 `feed_ids`
- 支持 `feed_links`
- 支持 `sub_ids`
- 支持 `keywords`

关键词会匹配：

- 订阅标题
- 标签
- 用户 ID
- Feed 标题
- Feed 链接

### `update_options(sub_id, user_id, **kwargs)`

只允许当前用户更新自己的订阅。

其中：

- `handlers` 会先转成 JSON 字符串
- `handlers_mode` 会做标准化

### `delete_all_by_feed_ids(feed_ids)`

按 Feed ID 删除关联订阅。Dashboard 删除 Feed 时会先按 Feed 找到订阅，再根据请求里的 `delete_push_history` 决定是否同步清理这些订阅或 Feed 对应的推送历史。

## User 仓储

### `get_or_create(user_id)`

用户是按 ID 软创建的。

这样做的原因是：

- 聊天命令和 Web API 都可能先引用用户，再产生用户记录
- 不需要额外的注册流程
- 订阅、TOML 导入、调度推送、测试推送和 XML 即时推送在写入订阅或推送历史前都应确保用户存在
- 启动期 schema 自愈会扫描 `rsshub_sub.user_id` 与 `rsshub_push_history.user_id`，补齐历史脏库里缺失的 `rsshub_user` 行

### `save(user)`

如果用户已存在，则更新可编辑字段；否则插入新行。

## PushHistory 仓储

### 关键词过滤

### `delete_by_user(user_id)`

删除指定用户的全部推送历史。这个接口只给显式清理用户审计历史的流程使用；Dashboard 删除用户默认只删除用户与订阅，保留推送历史。

### `delete_by_sub_ids(sub_ids)`

删除指定订阅对应的推送历史。这个接口只在删除订阅且请求显式要求 `delete_push_history=true` 时使用。

### `delete_by_feed_ids(feed_ids)`

删除指定 Feed 对应的推送历史。这个接口只在删除 Feed 且请求显式要求 `delete_push_history=true` 时使用。

### 关键词过滤

历史查询的关键词不是只查正文，还会查：

- `user_id`
- `source_type`
- `source_key`
- `content`
- `entry_title`
- `entry_link`
- `entry_guid`
- `feed_title`
- `feed_link`
- `platform_name`
- `target_session`
- `fail_reason`

数字关键词还会额外匹配：

- `id`
- `sub_id`
- `feed_id`

### 成功态幂等检查

`exists_success_by_scope_and_guid()` 是推送层幂等判断的核心：

- `source_type`
- `user_id`
- `target_session`
- `entry_guid`
- `source_key`（可选）

只有 `status=success` 才参与去重。

多 BOT 去重补充约束：

- 去重命中范围仍要求同一 `target_session`
- 只有最终 payload 等价时才视为同一条已成功投递
- 被压掉的重复投递不应伪装成成功发送，而应保留为 `status=skipped` 的审计记录

### 重试队列

`get_pending_for_retry()` 和 `get_and_mark_retrying()` 负责失败重试回收：

- `failed`
- `retry_count < max_retries`

其中：

- `failed_queue_capacity=0` 表示不上自动重试队列，不表示不写失败历史
- `max_retries` 对应 `failed_queue_max_retries`，只决定自动回收上限
- 超过上限的记录继续保留为失败历史，供查询与人工处理

并发重试时会先标记为 `retrying`，防止多 worker 重复捞取。

## 设计理由

仓储层最重要的不是“能查”，而是“查出来的对象能稳定服务于上层用例”。

所以这里的原则是：

- 应用层不直接写 SQL
- 仓储层负责字段兼容和查询细节
- Dashboard 的组合筛选只在仓储层收口
