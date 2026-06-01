# RSSHub for AstrBot

<div align="center">

<img src="https://raw.githubusercontent.com/FlanChanXwO/astrbot_plugin_rsshub/master/assets/logo.png" width="360" alt="rsshub"/>

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

## 命令一览

![命令一览](https://raw.githubusercontent.com/FlanChanXwO/astrbot_plugin_rsshub/master/assets/help/rsshelp_light.png)

## 协议

本项目基于 [AGPL](LICENSE) 协议开源。

## 致谢

- [RSS-to-Telegram-Bot](https://github.com/Rongronggg9/RSS-to-Telegram-Bot)
- [AstrBot](https://github.com/AstrBotDevs/AstrBot)
- [feedparser](https://github.com/kurtmckee/feedparser)
