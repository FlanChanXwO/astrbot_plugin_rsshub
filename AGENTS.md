# AGENTS.md — astrbot_plugin_rsshub

本文件只保留协作 agent 的入口规则。业务细节按需阅读 `docs/project/`，开发维护规则优先阅读 `docs/dev/maintenance.md`。

## 沟通语言

- 与用户沟通必须使用中文。

## 项目形态

- 这是一个 AstrBot RSSHub 插件，采用 DDD 分层。
- 管理功能属于 Plugin Pages + Web API。

主要目录：

- `src/domain/`: 领域实体、值对象、仓储协议。
- `src/application/`: 命令、查询、DTO、应用服务与用例编排。
- `src/infrastructure/`: 配置、持久化、抓取、消息发送、调度、知识库与工具适配。
- `src/interfaces/`: 聊天命令入口与 `web_api.py`。
- `pages/`: Plugin Pages 前端。
- `tests/`: 单元测试、集成测试与测试夹具。

## 阅读入口

- 任何改动前先看：`docs/dev/maintenance.md`
- 需要业务背景时看：`docs/project/README.md`
- 修改领域值、枚举、常量归属、配置语义时看：`docs/project/domain-model.md`
- 修改命令、AI tools、用户配置、推送历史时看：`docs/project/application.md`
- 修改平台发送、媒体、缓存、代理时看：`docs/project/platforms.md`
- 其他 `docs/project/` 主题文档只在触碰对应模块时阅读。

## 硬约束

- 不要把启动装配职责从 `bootstrap.py` 挪走。
- 除 `src/infrastructure/utils/paths.py` 外，不要直接调用 `get_astrbot_plugin_data_path()`。
- 从插件目录本地调试时，不要创建或使用 `<plugin>/data` 作为运行态目录。
- 会修改或导出用户资源的 Web API 必须接收真实 `user_id`；不要添加 `webadmin` fallback。
- 其他领域值、平台行为和配置边界不要写进本文件，放到 `docs/project/` 对应章节。

## 文档纪律

- 文档不是可选收尾。行为、边界、入口、配置、流程、架构或维护约定变化时，必须同步更新对应 `docs/`。
- 下列变化默认必须同步文档：
  - 命令行为或参数变化
  - Web API / Plugin Pages 交互变化
  - 配置项、继承语义、默认值或兼容规则变化
  - handler、AI、sender、KB、push history、queue、dedup 算法变化
  - 仓储查询语义、测试推送路径、失败重试语义变化
- 如果修改 repo-wide 维护规则或 agent 入口约定，同步更新 `AGENTS.md` 和 `CLAUDE.md`。

## 测试与检查命令

从插件目录运行：

```bash
python tests/run_tests.py -v
python tests/run_tests.py --category unit
python tests/run_tests.py --category integration
./tests/run_tests.sh --category unit
./tests/run_tests.sh --category integration
pytest tests/ -v
```

从 AstrBot 项目根目录运行：

```bash
uv run ruff format data/plugins/astrbot_plugin_rsshub
uv run ruff check data/plugins/astrbot_plugin_rsshub
```

## 更新策略

当架构、命令面、推送格式、配置路径或测试 / lint 流程变化时，同步更新 `CLAUDE.md` 和 `AGENTS.md`。

## 篇幅约束

`AGENTS.md` 和 `CLAUDE.md` 均不得超过 100 行；内容过长时拆入 `docs/dev/` 或 `docs/project/`。
