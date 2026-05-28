# 测试与回归检查

## 基础命令

| 场景 | 工作目录 | 命令 |
| --- | --- | --- |
| Python 格式化 | AstrBot 根目录 | `uv run ruff format data/plugins/astrbot_plugin_rsshub` |
| Python lint | AstrBot 根目录 | `uv run ruff check data/plugins/astrbot_plugin_rsshub` |
| 全量 pytest | 插件目录 | `pytest tests/ -v` |
| 单元分类测试 | 插件目录 | `python tests/run_tests.py --category unit` |
| 集成分类测试 | 插件目录 | `python tests/run_tests.py --category integration` |
| shell 分类单测 | 插件目录 | `./tests/run_tests.sh --category unit` |
| shell 分类集成 | 插件目录 | `./tests/run_tests.sh --category integration` |

> [!TIP]
> 从 IDE 直接运行脚本时，优先使用 `tests/run_tests.sh --category ...` 或 `python tests/run_tests.py --category ...`，避免当前 shell 的隐式目录影响结果。

## 分层验证矩阵

| 改动类型 | 最小检查 | 建议额外回归 | 关注点 |
| --- | --- | --- | --- |
| Python 业务逻辑 | 相关单元测试、`ruff check` | `FeedPollingService`、`NotificationDispatcher`、Web API、settings/config adapter、push history repository | 不要只跑被改函数附近的测试。 |
| Plugin Pages | `node --check pages/dashboard/app.js`、`node --check pages/dashboard/js/api.js` | 手工验证 tab 切换、loading 态、批量模式、详情面板、历史记录筛选 | 前端改动不要只看代码。 |
| 配置或迁移 | 相关配置 / migration 测试 | 旧配置兼容、`_conf_schema.json`、旧 sqlite、旧 TOML | 脏配置和旧库要能被容忍。 |
| sender / 媒体 | sender 单测、媒体下载相关测试 | OneBot、QQ Official、Telegram、Weixin OC 关键路径 | 这四个平台是当前明确测试覆盖点。 |
| handler runtime | handler 相关单测 | `ai_filter`、`ai_transform plaintext/xml`、trace 写入 | handler 失败默认不能阻断 RSS。 |

## 高风险改动清单

| 改动 | 风险 | 建议 |
| --- | --- | --- |
| 命令签名变化 | 破坏 AstrBot 命令解析或 GreedyStr 兼容 | 补命令解析测试。 |
| sender 行为变化 | 平台吞文本、媒体类型错误、fallback 丢失 | 至少覆盖相关平台 sender。 |
| push history 字段变化 | 审计、重试、筛选回退 | 检查 repository、Web API、Dashboard。 |
| handler runtime 行为变化 | AI 失败阻断、trace 丢失、skip 语义错 | 保留失败放行和 skipped history 测试。 |
| 订阅继承规则变化 | 用户/订阅配置生效错误 | 覆盖 `-100` 继承链。 |
| Routes KB 同步链路变化 | 文档同步任务状态或 manifest diff 错误 | 覆盖新增、更新、删除、无变化。 |

## 回归检查清单

- [ ] `/sub_test` 仍然是真实发送，不是 preview。
- [ ] `push_history.content` 不泄漏原始 HTML 标签。
- [ ] `raw_xml` 仍保留原始条目 XML。
- [ ] `-100` 继承规则没有被破坏。
- [ ] OneBot 媒体/文本顺序没有回退。
- [ ] Plugin Pages 没有重新暴露 `link_preview`。
