# 开发环境与本地调试

## 前置要求

- Python 3.12+
- AstrBot 主仓库本地开发环境
- 推荐使用 `uv`

## 本地代码位置

插件通常位于：

```text
AstrBot/data/plugins/astrbot_plugin_rsshub
```

## 常用目录

```text
assets/      # 静态资源与帮助图模板
pages/       # Plugin Pages 前端
src/         # DDD 主代码
tests/       # 单元与集成测试
docs/        # 项目、开发、使用文档
skills/      # 给 AI agent 的 skill
```

## 运行与调试原则

### 启动入口

项目运行通常启动 AstrBot 主仓库顶层入口，而不是直接运行插件目录内的文件。

本地工作区常见入口：

```bash
python /Users/flanchan/Development/SourceCode/GithubProjects/AstrbotPluginDev/main.py
```

如果工作区路径不同，就在 AstrBot 根目录运行对应的顶层 `main.py`。

### 数据目录

不要把运行时数据写回插件仓库下的 `data/`。

本插件统一通过路径工具访问：

- `get_plugin_data_dir()`
- `get_plugin_cache_dir()`
- `get_plugin_export_dir()`

### 启动结构

启动分工见 [`../project/architecture.md`](../project/architecture.md#启动结构)。本地调试时不要把 startup ownership 从 `bootstrap.py` 挪回入口文件。

### Plugin Pages

前端位于 `pages/dashboard/`，主要由：

- `index.html`
- `app.js`
- `js/api.js`
- `css/*.css`

构成。前端行为依赖 AstrBot Plugin Pages bridge，不是一个独立 SPA。

## 测试与检查命令

命令清单统一维护在 [`testing.md`](./testing.md)，本文件不重复列出。

## 改动前先确认的几件事

- 改的是命令语义、配置模型，还是 UI 行为？
- 这次改动是否会影响 `push_history` 或 sender 兼容性？
- 这次改动是否需要同步更新 README 与 docs？
