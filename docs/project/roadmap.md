# 路线图与现状

## 当前阶段

项目目前处于 v2.0.0 收口阶段，已经完成的重点包括：

- 命令语义回归收口
- `link_preview` 全量移除
- 类型化配置模型与运行态设置统一到 `src/infrastructure/config/models/`，其中 `src/infrastructure/config/datamodels.py` 仅作为兼容导出
- handler registry 与内置 AI handlers 上线
- Plugin Pages 管理面板大幅扩展
- RSSHub Routes 知识库同步能力接入
- 推送历史、数据管理、跨标签筛选联动补全

## 当前未完成但已定方向

### 文档

- `project/` 与 `dev/` 已完成首轮收口
- `usage/` 仍待继续拆分

### 处理器生态

- 当前仅展示和执行内置 handler
- Plugin Pages 中的“安装处理器”入口暂时禁用
- external handler 数据可保存/展示，但运行时不执行

### 更长期的演进

依据 [`PLAN.md`](../PLAN.md)，后续仍可能继续推进：

- 平台无关组件契约
- 独立 extension runtime
- registry 安装流
- 更强的 AI formatter / transform 能力

`PLAN.md` 是长期方案草案；真正实施时以当时的 issue、PR 和变更说明为准。

## 建议的文档维护策略

后续继续推进时，建议按下面的顺序维护文档：

1. 先更新 `project/overview.md` 中的边界与定位
2. 再更新 `project/architecture.md` 中的实际链路
3. 最后更新 `README.md` 的外部说明

不要只改 README，不改项目文档。否则很快会再次出现入口文档和实现脱节。
