# CLAUDE.md — astrbot_plugin_rsshub

本文件只保留 Claude 协作入口规则。业务细节按需阅读 `docs/project/`，开发维护规则优先阅读 `docs/dev/maintenance.md`。

## 沟通语言

必须使用中文与用户交流。

## 项目形态

- **语言**: Python 3.10+
- **框架**: AstrBot plugin system
- **架构**: DDD 分层
- **许可证**: AGPL

主要目录：

```text
src/domain/          领域实体、值对象、仓储协议
src/application/     命令、查询、DTO、应用服务与用例编排
src/infrastructure/  配置、持久化、抓取、消息发送、调度、知识库与工具适配
src/interfaces/      聊天命令入口与 web_api adapter
pages/               Plugin Pages 前端
tests/               单元测试、集成测试、测试夹具和 mock
```

## 阅读入口

- 任何改动前先看：`docs/dev/maintenance.md`
- 需要业务背景时看：`docs/project/README.md`
- 修改领域值、枚举、常量归属、配置语义时看：`docs/project/domain-model.md`
- 修改命令、AI tools、用户配置、推送历史时看：`docs/project/application.md`
- 修改平台发送、媒体、缓存、代理时看：`docs/project/platforms.md`
- 其他 `docs/project/` 主题文档只在触碰对应模块时阅读。

## 技能

如果当前会话可用，修改本插件时优先参考 `astrbot-dev-skill`。它对 AstrBot 命令装饰器、Plugin Pages bridge、统一会话 ID 和平台适配边界有帮助。

## 硬约束

- 不要把启动装配职责从 `bootstrap.py` 挪走。
- 除 `src/infrastructure/utils/paths.py` 外，不要直接调用 `get_astrbot_plugin_data_path()`。
- 从插件目录本地调试时，不要创建或使用 `<plugin>/data` 作为运行态目录。
- 会修改或导出用户资源的 Web API 必须接收真实 `user_id`；不要添加 `webadmin` fallback。
- 其他领域值、平台行为和配置边界不要写进本文件，放到 `docs/project/` 对应章节。

## 文档纪律

- 文档是改动的一部分。代码改动导致现有说明失真时，必须在同一 patch 中更新相关 `docs/`。
- 命令行为、Web API/Page 行为、配置语义、handlers、sender、KB sync、push history、queue/retry、dedup、仓储查询和测试推送流程变化时，通常需要更新文档。
- repo-wide 约束或 agent 入口说明变化时，同步更新 `AGENTS.md` 和 `CLAUDE.md`。

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

## 维护

当架构、命令面、推送格式、配置路径或测试 / lint 流程变化时，同步更新 `AGENTS.md` 和 `CLAUDE.md`。

## 篇幅约束

`AGENTS.md` 和 `CLAUDE.md` 均不得超过 100 行；内容过长时拆入 `docs/dev/` 或 `docs/project/`。
