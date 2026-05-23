# 订阅命令链与测试推送

## 负责什么

这一章覆盖聊天命令入口到应用命令的完整分支，重点是：

- `/sub`
- `/unsub`
- `/sub_list`
- `/sub_profile`
- `/sub_session`
- `/sub_test`

## 为什么命令链要单独写

命令入口是插件最常见的用户操作路径，但它不能承载所有业务规则：

- 入口负责解析参数
- 应用命令负责业务
- 仓储负责持久化
- dispatcher 负责真实推送

这样拆开后，Web API、LLM tools、命令入口才能共用同一套用例。

## `/sub`

### 入口行为

- 支持批量 URL
- 过滤非 http/https
- 逐条执行订阅

### 应用层路径

`handle_sub()` -> `SubscribeFeedCommand.execute()`

### 核心算法

1. 规范化 URL
2. 抓取 feed 获取标题
3. `get_by_link()` 查重
4. 没有则创建 Feed
5. 创建 Subscription
6. 如有会话默认值，则应用 `session_defaults`

### 设计理由

- 订阅按 URL 幂等
- 订阅时先抓标题，能让列表更可读
- 会话默认值在订阅创建后再应用，便于保留用户显式输入

## `/unsub`

### 入口行为

- 支持 ID / URL 混合批量
- 逐个取消

### 设计理由

URL 和 ID 兼容是为了迁移旧用法，同时满足批量清理。

## `/sub_list`

### 入口行为

- 只看当前会话
- 支持分页

### 设计理由

这不是全局管理页，而是当前会话的聊天视角。

## `/sub_profile` 与 `/sub_session`

这两组命令负责修改订阅/用户/会话默认配置。

当前已经收敛为：

- `sub_profile set|get`
- `sub_session set|get`

它们的目标是减少旧命令分裂带来的维护成本。

## `/sub_test`

### 两种目标

#### 1. 目标是 `sub_id`

这是“真实链路单条模拟发送”：

1. 读取订阅
2. 补齐推送会话和平台
3. 抓取对应 feed
4. 取最新 1 条
5. 走 dispatcher

这条路径会应用：

- 订阅默认配置
- 用户默认配置
- handlers 链
- sender 适配
- push history 记录

如果真实 sender 返回失败，测试推送会优先展示 sender 的失败原因，例如平台文件大小限制、会话不可用或媒体上传失败；只有在订阅没有命中、通知关闭、handler 跳过或去重时，才提示“未进入正式发送链路”。

#### 2. 目标是 URL

这是“URL 直发测试”：

- 不读取订阅
- 不应用订阅配置
- 只按 URL 抓取并直推

### 为什么要双路径

- `sub_id` 模式适合验证真实配置
- `URL` 模式适合快速排查 feed 本身
- 聊天命令不支持额外条目范围参数；多条测试请通过 Plugin Pages 或专门调试入口处理。

## 订阅链的完整分层

1. `main.py`：命令装饰器和参数入口
2. `src/interfaces/handlers/*.py`：命令解析与对话语义
3. `application/commands/*.py`：业务编排
4. `domain/`：实体规则
5. `infrastructure/`：存储、抓取、发送适配

这样拆的目的，是让同一套业务能同时服务命令、Web API 和 LLM tools。
