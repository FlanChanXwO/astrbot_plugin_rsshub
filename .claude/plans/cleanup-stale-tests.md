# 清理 RSSHub 插件遗留测试失败（16 个 pre-existing failures）

## Context

修复 `media.gif_transcode` wiring bug 时（commit `fd186d19`），跑完整 `pytest tests/` 发现还有 16 个测试失败，均为**本次改动之前就存在**的债。需要清理它们让 CI 重回绿色。

这些失败不影响 runtime 行为；只是测试基础设施与代码同步度落后导致。

工作目录：`/Users/flanchan/Development/SourceCode/GithubProjects/astrbot-plugin-dev/data/plugins/astrbot_plugin_rsshub`

分支：当前在 `fix/code-review-findings`。可以直接在此分支上 commit，或新建一个 `chore/cleanup-stale-tests` 子分支隔离。

## 三组独立 issue

### Issue A：死 API 测试遗留（8 个 fail，最大组）

`Extension` 与 `PluginManager` 两个 class **早已从源码中删除**（疑似 v2.0 plugin extension 系统下线时清理）。`EventBus` 仍然存在并被生产代码使用，**不要删**。

#### A1. 死符号清理 —— `src/infrastructure/__init__.py`

`_EXPORT_MAP` 中 4 个条目指向不存在的符号：

```python
"Extension": ("messaging", "Extension"),              # 删
"PluginManager": ("messaging", "PluginManager"),      # 删
"get_plugin_manager": ("messaging", "get_plugin_manager"),  # 删
"on_event": ("messaging", "on_event"),                # 删
```

验证方法（已在调研阶段跑过）：

```bash
python3 -c "
import sys; sys.path.insert(0, '.')
import src.application
from src.infrastructure import messaging
for s in ['Extension','PluginManager','get_plugin_manager','on_event']:
    print(s, '-> MISSING' if not hasattr(messaging, s) else 'EXISTS')
"
```

应该全部输出 MISSING。其余的 `EventBus`、`BaseEvent`、`get_event_bus`、`register_sender` 等都是有效的，**留下不动**。

#### A2. 删除 `tests/unit/infrastructure/test_event_system.py` 中已死的两个 class 的测试

文件有 4 个 test class：

- `TestEventBus`（保留 —— EventBus 还在）
- `TestExtension`（删 —— class 已不存在）
- `TestPluginManager`（删 —— class 已不存在）
- 其他若有，按 `from astrbot_plugin_rsshub.src.infrastructure.messaging import X` 的 X 是否存在为准

操作：保留 `TestEventBus` 段（含 4 个测试方法），删 `TestExtension` 段和 `TestPluginManager` 段。删后 file 仍可运行；如果删后文件几乎空了，可整文件删除并在 commit message 说明。

#### A3. `conftest.py` 注册 `main.py` 为可导入子模块

3 个 `test_command_handlers_regression.py` 测试用 `importlib.import_module("astrbot_plugin_rsshub.main")` 加载主模块。当前 `tests/conftest.py:45-53` 只注册了 `bootstrap.py`，没注册 `main.py`。

在 conftest 第 53 行后追加同款 4 行：

```python
# 注册 main 模块（位于插件根目录）
_main_path = PLUGIN_DIR / "main.py"
_main_spec = importlib.util.spec_from_file_location(
    "astrbot_plugin_rsshub.main",
    str(_main_path),
)
_main_mod = importlib.util.module_from_spec(_main_spec)
sys.modules["astrbot_plugin_rsshub.main"] = _main_mod
# 注意：不要在 conftest 中立刻 exec_module，因为 main.py 可能依赖更多 AstrBot mock，
# 让测试自己 importlib.import_module 时再执行。如果 import 时仍失败，回退方案是
# 在 exec_module 之前先把当前已 mock 的 astrbot.* 子模块全部覆盖到 main 期望的命名空间。
_main_spec.loader.exec_module(_main_mod)
_pkg.main = _main_mod
```

如果 `exec_module` 失败（因为 `main.py` 引了某个 conftest 尚未 mock 的 astrbot 符号），加 `try/except` 包住 `exec_module`，并在 `except` 分支只把 spec 占位放进 `sys.modules`，让测试侧 `import_module` 时按需触发，并把错误暴露在测试本身。

### Issue B：`caching` 名字冲突（4 个 fail）

#### 根因（已实证）

`src/infrastructure/utils/__init__.py` 用 lazy `__getattr__` + 同名子模块（`caching.py` 里定义函数也叫 `caching`）。当 pytest 触发 `from astrbot_plugin_rsshub.src.infrastructure.utils import caching` 时，Python 优先解析为子模块 `astrbot_plugin_rsshub.src.infrastructure.utils.caching`（即 module 对象），**绕过** `__getattr__`，导致 `caching` 拿到 module 而不是 function。

```python
# 调研期实证
>>> from astrbot_plugin_rsshub.src.infrastructure.utils import caching
>>> type(caching)
<class 'module'>            # ← 期望是 function
>>> callable(caching)
False
```

#### 修复方案（推荐方式）

在 `src/infrastructure/utils/__init__.py` 的 `__getattr__` 之前**显式 from-import**几个会和子模块同名的符号，让它们落到包命名空间，从而 shadow 子模块。

需要 shadow 的符号：grep `_EXPORTS` map 中 `key == module_name` 的条目。当前已知：

- `caching`（同 caching.py）

其他 lazy entry 的 key（`BaseCache`、`get_memory_cache` 等）与子模块名不冲突，不需要 eager import。

具体改法：在 `src/infrastructure/utils/__init__.py` 第 50 行（`_EXPORTS = {...}` 定义之前或之后均可）加：

```python
# Eager re-export of names that collide with submodule names. Without these,
# `from utils import caching` returns the caching submodule, not the function.
from .caching import caching  # noqa: F401
```

跑验证：

```bash
python -m pytest tests/unit/utils/test_caching.py -v
# 期望：从 4 fail 变成 all pass
```

#### 替代方案（不推荐）

把 `caching.py` 文件重命名为 `cache_decorator.py`，更新所有引用。改动面太大，不必。

### Issue C：知识库生成器测试缺前置文件（1 个 fail）

`tests/unit/test_route_knowledge_generator.py::test_route_knowledge_generator_writes_metadata` 引用 `.github/scripts/generate_knowledgebase.py`，但该文件**在插件目录和 runtime 根目录都不存在**（已验证）—— 它在外部 KB 仓库 `FlanChanXwO/rsshub-routes-knowledgebase` 里。

#### 修复方案

在该 test function 顶部加 skipif：

```python
import pytest
from pathlib import Path

_KB_SCRIPT = Path(__file__).resolve().parents[2] / ".github" / "scripts" / "generate_knowledgebase.py"

@pytest.mark.skipif(
    not _KB_SCRIPT.exists(),
    reason="KB generator script lives in external repo; only present in CI envs that vendor it",
)
def test_route_knowledge_generator_writes_metadata(...):
    ...
```

或者删除整个测试文件 —— 如果该测试**只**在 CI 的某个特定流程跑（需用户/agent 确认是否有 CI workflow 显式依赖此测试）。**保守先 skipif**。

## 实施顺序

1. **Issue B**（10 min）：改动最小、风险最低，先做。一处 `from .caching import caching` 即解决 4 个 fail。
2. **Issue C**（5 min）：加 skipif，零风险。
3. **Issue A**（30 min）：
   - A1 先（删 4 条 export）
   - A2 跟上（删 test_event_system.py 中两个死 class 的测试段）
   - A3 最后（conftest 加 main 注册，3 个测试解锁）
   - 每一步跑 `pytest tests/` 验证不引入新 fail

## 验证

每一组修完跑：

```bash
python -m pytest tests/ -v 2>&1 | tail -20
```

最终目标：`pytest tests/` 全过（除明确 skip 的）。

Issue B 单独验证：

```bash
python -m pytest tests/unit/utils/test_caching.py -v
# 应全 pass
```

Issue A1 验证：

```bash
python -m pytest tests/unit/test_compat_exports.py -v
# 应全 pass
```

Issue A2 验证：

```bash
python -m pytest tests/unit/infrastructure/test_event_system.py -v
# 应全 pass（剩下的 TestEventBus 段）
```

Issue A3 验证：

```bash
python -m pytest tests/unit/test_command_handlers_regression.py -v
# 应全 pass
```

Issue C 验证：

```bash
python -m pytest tests/unit/test_route_knowledge_generator.py -v
# 应显示 skipped
```

## Lint / format

每次修改后跑：

```bash
ruff check src/ tests/ --fix
ruff format src/ tests/
python3 -m compileall -q .
```

## Commit 切分建议

每个 issue 独立 commit，便于 review：

```
chore(tests): fix caching import shadowing (4 tests)
chore(tests): skip route-knowledge-generator test when CI script absent
chore(tests): remove dead Extension/PluginManager exports and tests
```

如果在意 commit 数，A1+A2+A3 可合成一个 `chore(tests): clean up legacy plugin extension references`。

## 关键文件清单

- `src/infrastructure/__init__.py` — A1 删 4 个 _EXPORT_MAP 条目
- `src/infrastructure/utils/__init__.py` — B 加 1 行 eager from-import
- `tests/conftest.py` — A3 加 4 行注册 main.py
- `tests/unit/infrastructure/test_event_system.py` — A2 删 TestExtension + TestPluginManager 两段
- `tests/unit/test_route_knowledge_generator.py` — C 加 skipif

## 边界 / 不要做

- **不要动** `EventBus`、`BaseEvent`、`get_event_bus`、`register_sender`、`NotificationServiceImpl` 等 —— 它们仍被生产代码使用。grep 确认前别动。
- **不要重命名** `caching.py` 文件 —— 改动面比 eager import 大 10×，无收益。
- **不要在 A3 中**直接修改 `main.py` 让它"测试友好"—— 应通过 conftest 注册搞定，让测试侧用现有的 `importlib.import_module` 路径。
- 整批改完前不要 `git push`，确保本地 `pytest tests/` 全过。
