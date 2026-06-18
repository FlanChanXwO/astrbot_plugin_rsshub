# RSSHub for AstrBot

<div align="center">

<img src="https://raw.githubusercontent.com/FlanChanXwO/astrbot_plugin_rsshub/master/assets/logo.png" width="360" alt="rsshub"/>

<br/>

<img src="https://count.getloli.com/@astrbot_plugin_rsshub?name=astrbot_plugin_rsshub&theme=rule34&padding=7&offset=0&align=top&scale=1&pixelated=1&darkmode=auto" alt="Moe Counter">


**AstrBot RSS 订阅插件**

[![License: AGPL](https://img.shields.io/badge/License-AGPL-blue.svg)](https://opensource.org/licenses/agpl-3.0)
![Python Version](https://img.shields.io/badge/Python-3.10%2B-blue)
![AstrBot](https://img.shields.io/badge/AstrBot-%E2%89%A54.24.0-green)
![Platform](https://img.shields.io/badge/Platform-Windows%20%7C%20Linux%20%7C%20MacOS-lightgrey)
[![Last Commit](https://img.shields.io/github/last-commit/FlanChanXwO/astrbot_plugin_rsshub)](https://github.com/FlanChanXwO/astrbot_plugin_rsshub/commits/master)

</div>

## 项目简介

`astrbot_plugin_rsshub` 为 AstrBot 提供 RSS/Atom 订阅、定时推送、富媒体解析、失败重试、订阅导入导出、AI tool 管理和 Plugin Pages 管理界面。

核心能力：

- RSS/Atom 订阅与多会话推送。
- 图片、音频、视频、文件、表格图片和平台差异化发送。
- 订阅级、用户级、会话级配置继承。
- AI 订阅、查询、配置和 XML 即时推送工具。
- Plugin Pages 可视化管理订阅、Feed、用户、推送历史和 RSSHub Routes 知识库。
- TOML 订阅导入导出与失败推送重试。

## 安装

推荐在 AstrBot 插件市场搜索 `RSSHub` 安装。

手动安装：

```bash
cd AstrBot/data/plugins
git clone https://github.com/FlanChanXwO/astrbot_plugin_rsshub.git
```

安装后重启 AstrBot 或重载插件。

## 文档导航

- 使用文档：[`docs/usage/README.md`](./docs/usage/README.md)
- 命令说明：[`docs/usage/commands.md`](./docs/usage/commands.md)
- 配置说明：[`docs/usage/configuration.md`](./docs/usage/configuration.md)
- 管理界面：[`docs/usage/plugin-pages.md`](./docs/usage/plugin-pages.md)
- AI tools：[`docs/usage/ai-tools.md`](./docs/usage/ai-tools.md)
- 兼容性说明：[`docs/usage/compatibility.md`](./docs/usage/compatibility.md)
- 项目与架构：[`docs/project/README.md`](./docs/project/README.md)
- 开发与贡献：[`docs/dev/README.md`](./docs/dev/README.md)

## 开发与测试

运行完整测试需要系统 FFmpeg（或已有插件缓存）和测试媒体文件。公网 m3u8 测试需额外设置 `RSSHUB_RUN_NETWORK_TESTS=1`。详见 [`docs/dev/README.md`](./docs/dev/README.md)。

`requirements.txt` 只包含插件运行时依赖。运行 pytest 或重新生成帮助图前，请在 AstrBot 根目录安装开发依赖：

```bash
uv pip install --python .venv/bin/python -r data/plugins/astrbot_plugin_rsshub/requirements-dev.txt
```

测试媒体文件放在 `tests/data/` 下（已排除版本控制，需开发者自行准备）：

| 文件名 | 说明 |
|--------|------|
| `silent-video.mp4` | 无声短视频（GIF 转换测试用） |
| `audio-video.mp4` | 有声短视频（音频检测测试用） |
| `sample-image.jpg` | 测试图片 |
| `sample-gif.gif` | 测试动图 |
| `sample-audio.mp3` | 测试音频 |

## 命令一览

![命令一览](https://raw.githubusercontent.com/FlanChanXwO/astrbot_plugin_rsshub/master/assets/help/rsshelp_light.png)

## 协议

本项目基于 [AGPL](LICENSE) 协议开源。

## 致谢

- [RSS-to-Telegram-Bot](https://github.com/Rongronggg9/RSS-to-Telegram-Bot)
- [AstrBot](https://github.com/AstrBotDevs/AstrBot)
- [feedparser](https://github.com/kurtmckee/feedparser)
