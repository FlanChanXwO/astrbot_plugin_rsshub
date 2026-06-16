# Plan — 清理 RSSHub 插件遗留测试失败

## 背景

代码库当前有 16 个 pre-existing 测试失败，均为本次改动之前就存在的债。来自 `.claude/plans/cleanup-stale-tests.md` 的详细分析。

## 三个独立 Issue

### Issue A：死 API 测试遗留（8 个 fail）
- `Extension` / `PluginManager` class 早已从源码删除
- A1：删除 `src/infrastructure/__init__.py` 中 `_EXPORT_MAP` 的 4 个失效条目
- A2：删除 `tests/unit/infrastructure/test_event_system.py` 中 `TestExtension` 和 `TestPluginManager` 测试段
- A3：在 `tests/conftest.py` 注册 `main.py` 为可导入子模块，解锁 3 个回归测试

### Issue B：caching 名字冲突（4 个 fail）
- `src/infrastructure/utils/__init__.py` 中 `caching` 函数名与 `caching.py` 子模块名冲突
- 修复：加一行 `from .caching import caching` eager import

### Issue C：知识库生成器测试缺前置文件（1 个 fail）
- KB generator 脚本在外部仓库，不在当前插件目录
- 修复：加 `@pytest.mark.skipif` 条件跳过

## 实施顺序

1. Issue B（最低风险，最快，1 行改）
2. Issue C（极低风险，加 skipif）
3. Issue A（最大组，3 个子步骤）

## 验证方式

每组修完跑 `pytest tests/ -v` 确认不引入新 fail。最终目标：全部通过或合理 skip。

## 风险

- **低**：所有改的都是测试基础设施或死代码引用，不动生产逻辑
- A3 的 `exec_module` 可能因缺少 mock 失败，需 `try/except` 保护

## 回滚

每个 task 独立 commit，出问题可逐个 revert。

## 默认假设

- 分支 `fix/code-review-findings` 当前状态是干净的（没有未提交的改动）
- pytest 环境已正确配置，可直接运行
- `ruff`、`python3 -m compileall` 等工具可用
