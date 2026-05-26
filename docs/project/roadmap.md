# 路线图与现状

## 当前阶段

项目已经完成 v2.0.0 后的核心收口，当前重点转向处理器内部通信与后续扩展运行时边界。已完成的重点包括：

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
- 内置处理器已经接入当前 handler runtime
- 下一步重点是处理器内部通信契约、上下文、trace 和错误模型
- external handler 数据可保存/展示，但运行时不执行

### 更长期的演进

依据 [`PLAN.md`](../PLAN.md)，后续计划已经收敛到 Stage 3：

- 稳定 `HandlerRequest` / `HandlerResult` / `HandlerTraceEvent`
- 迁移内置 `ai_filter` / `ai_transform` 到统一消息契约
- 为外部处理器 JSON-safe payload 和 RPC 边界做预备
- Registry、完整 Extension Runtime、作者辅助 skill 暂缓到通信契约稳定之后

`PLAN.md` 是当前后续草案；真正实施时以当时的 issue、PR 和变更说明为准。

## 建议的文档维护策略

后续继续推进时，建议按下面的顺序维护文档：

1. 先更新 `project/overview.md` 中的边界与定位
2. 再更新 `project/architecture.md` 中的实际链路
3. 最后更新 `README.md` 的外部说明

不要只改 README，不改项目文档。否则很快会再次出现入口文档和实现脱节。
