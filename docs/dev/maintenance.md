# 维护规则

本文面向维护者和协作 agent，记录开发时需要遵守的仓库级规则。业务细节不要继续塞进 `AGENTS.md` 或 `CLAUDE.md`，应拆到 `docs/project/` 的对应主题文档。

## 文档同步

- 文档不是可选收尾。
- 行为、边界、入口、配置、流程、架构或维护约定变化时，必须同步更新对应文档。
- 下列变化默认需要更新文档：
  - 命令行为或参数变化
  - Web API / Plugin Pages 交互变化
  - 配置项、继承语义、默认值或兼容规则变化
  - handler、AI、sender、KB、push history、queue、dedup 算法变化
  - 仓储查询语义、测试推送路径、失败重试语义变化
- 修改 repo-wide 维护规则或 agent 入口约定时，同步更新 `AGENTS.md` 和 `CLAUDE.md`。

## 入口与分层

入口与分层事实统一维护在 [`../project/architecture.md`](../project/architecture.md)。本文件只记录维护要求：不要把启动装配职责从 `bootstrap.py` 挪走，业务规则、平台适配和入口适配不要互相污染。

## 本地路径

- 插件运行数据、缓存和导出路径统一通过 `src/infrastructure/utils/paths.py` 获取。
- 不要在其他位置直接调用 `get_astrbot_plugin_data_path()`。
- 从插件目录本地调试时，不应创建或使用 `<plugin>/data` 作为运行态目录。

## 配置维护

- 配置模型和配置面边界见 [`../project/domain-model.md`](../project/domain-model.md#配置面边界)。
- 启动配置必须根据 `_conf_schema.json` 自愈：
  - 补缺失默认值
  - 删除未知或废弃字段
  - 转换可恢复数字值
  - clamp slider 范围
  - 重置非法 options
- `_conf_schema.json` 字段新增、删除、类型变化时，必须更新配置自愈回归测试。
- sender strategy 的运行时语义见 [`../project/platforms.md`](../project/platforms.md)，不要在维护文档里复制平台字段清单。

## 代码组织

- 领域值、枚举语义和常量归属见 [`../project/domain-model.md`](../project/domain-model.md)。
- formatter 只负责把解析后的 entry/media 格式化给 sender。
- 不要把翻译、增强、route lookup 或订阅命令 fallback 放进 formatter。
- AI 过滤属于 `ContentHandlerRuntime`。

## Plugin Pages 维护

- Plugin Pages 职责见 [`../project/architecture.md`](../project/architecture.md#管理界面职责) 与 [`../project/web_api.md`](../project/web_api.md)。
- 用户拥有资源的 Web API 写操作必须传入真实 `user_id`。
- 不要恢复 `webadmin` fallback 用户。
- Plugin Pages 不暴露 `link_preview` 控件或状态。

## 依赖管理

- 依赖分两层：`requirements.txt` 是最终用户安装的 runtime 依赖；`requirements-dev.txt` 通过 `-r requirements.txt` 继承，再追加测试与帮助图生成所需的开发依赖。安装命令见 [`testing.md`](./testing.md)。
- Runtime 依赖归属（删除或软依赖化前必须先评估这些角色）：
  - `feedparser`：RSS / Atom 解析核心，见 `src/infrastructure/fetcher/rss/`。
  - `beautifulsoup4`：HTML 内容清洗、表格解析与 Feed 自动发现，见 `src/application/services/html_parser.py`、`src/infrastructure/rendering/table_image_renderer.py`、`src/infrastructure/fetcher/rss/discoverer.py`。
  - `lxml`：`BeautifulSoup(html, "lxml")` 的 parser backend，三处硬编码引用，性能与畸形 HTML 容错优先。
  - `pillow`：仅服务"表格 → PNG"渲染（`table_image_renderer.py`），辅以 `src/infrastructure/utils/media_integrity.py` 的图片 verify。
  - `filetype`：RSS enclosure 与已下载媒体的类型识别（`src/infrastructure/utils/media_type_detector.py`），存在手写 magic bytes fallback 但保留以提高识别率。
  - `aiohttp-socks`：Telegraph SOCKS5 代理（aiohttp 原生不支持 SOCKS），见 `src/infrastructure/messaging/senders/telegraph_client.py`。
- 媒体处理边界：音视频 / GIF / 转码一律走 FFmpeg（见 [`../project/platforms.md`](../project/platforms.md) 与 `src/infrastructure/utils/ffmpeg_helper.py`）；`pillow` 只承担表格 PNG 渲染和图片完整性校验，不承担音视频处理。
- Dev 依赖归属：`pytest` + `pytest-asyncio` 服务测试，`jinja2` + `playwright` 服务 `scripts/generate_rsshelp_image.py` 的帮助图渲染；这类依赖体积可观（playwright + browsers 数百 MB），不得塞进 runtime。
- 后续想减小安装体积时，优先评估 `lxml` 软依赖化（fallback 到标准库 `html.parser`），而不是动 `pillow` / `filetype`——它们的角色已固化。

## 测试与检查

常用命令见 [`testing.md`](./testing.md)。涉及下列行为时，优先补回归测试：

- schema 自愈
- 数据库迁移
- 命令签名和参数解析
- Web API 筛选和批量操作
- sender 降级和媒体缓存
- push history retry / dedup / skipped 审计
- handler 链继承和 trace

## 仓库体积

- 插件仓库总大小**严格不得超过 16 MB**。这是硬上限，提交或合并前必须确认未越界。
- 不要把字体、模型权重、媒体样例、构建产物或大体积二进制资源直接纳入仓库；运行期所需的大文件应按需下载到数据目录（参见字体运行时下载机制）。
- 新增任何二进制或大体积资源前，先评估对总体积的影响；接近上限时优先改为外部下载或精简。

## 已移除能力

已移除能力按主题记录在项目文档中。本节只保留维护要求：修改相关入口前先阅读对应专题，不要凭旧记忆恢复已经移除的入口或配置面。

相关语义见：

- [`../project/application.md`](../project/application.md#已移除的应用能力)
- [`../project/platforms.md`](../project/platforms.md#媒体下载与缓存)
- [`../project/web_api.md`](../project/web_api.md)
