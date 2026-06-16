# Tasks — 清理 RSSHub 插件遗留测试失败

## Task 1：Issue B — 修复 caching 名字冲突

- **文件**：`src/infrastructure/utils/__init__.py`
- **改动**：在 `_EXPORTS` 定义附近加 `from .caching import caching  # noqa: F401`
- **验证**：`pytest tests/unit/utils/test_caching.py -v` 全 pass
- **风险**：零

### 实际做了什么
_(待填写)_

### 验证证据
_(待填写)_

### 剩余风险
_(待填写)_

---

## Task 2：Issue C — skip KB generator 测试

- **文件**：`tests/unit/test_route_knowledge_generator.py`
- **改动**：在目标 test function 上加 `@pytest.mark.skipif` 条件跳过
- **验证**：`pytest tests/unit/test_route_knowledge_generator.py -v` 显示 skipped
- **风险**：零

### 实际做了什么
_(待填写)_

### 验证证据
_(待填写)_

### 剩余风险
_(待填写)_

---

## Task 3：Issue A1 — 删除 _EXPORT_MAP 死条目

- **文件**：`src/infrastructure/__init__.py`
- **改动**：删除 4 个指向不存在符号的 _EXPORT_MAP 条目
- **验证**：`pytest tests/unit/test_compat_exports.py -v` 全 pass
- **风险**：低（仅删 export 映射，不影响其他代码）

### 实际做了什么
_(待填写)_

### 验证证据
_(待填写)_

### 剩余风险
_(待填写)_

---

## 🔍 集中检查 #1（Task 1-3 完成后的 Debug 循环）

- 跑 `pytest tests/ -v` 全量
- 确认 Issue B + C + A1 共 ~13 个 fail 已清除
- 确认无新 fail 引入
- 跑 `ruff check src/ tests/` 确认无 lint error
- 回看 `input.md` 确认不偏离需求

### 检查结论
_(待填写)_

### 发现的问题
_(待填写)_

---

## Task 4：Issue A2 — 删除死测试段

- **文件**：`tests/unit/infrastructure/test_event_system.py`
- **改动**：删除 `TestExtension` 和 `TestPluginManager` 两个 test class（保留 `TestEventBus`）
- **验证**：`pytest tests/unit/infrastructure/test_event_system.py -v` 全 pass（剩余 TestEventBus 段）
- **风险**：低

### 实际做了什么
_(待填写)_

### 验证证据
_(待填写)_

### 剩余风险
_(待填写)_

---

## Task 5：Issue A3 — conftest 注册 main.py

- **文件**：`tests/conftest.py`
- **改动**：追加 main.py 的 module spec 注册，用 try/except 包 exec_module
- **验证**：`pytest tests/unit/test_command_handlers_regression.py -v` 全 pass
- **风险**：中（exec_module 可能因为缺少 mock 失败，需 try/except 保护）

### 实际做了什么
_(待填写)_

### 验证证据
_(待填写)_

### 剩余风险
_(待填写)_

---

## Task 6：全量验证 + Lint

- **改动**：无新增代码，仅最终验证
- **验证**：`pytest tests/ -v` 全过或合理 skip
- **验证**：`ruff check src/ tests/` 无 error
- **验证**：`python3 -m compileall .` 全通过
- **风险**：零

### 实际做了什么
_(待填写)_

### 验证证据
_(待填写)_

### 剩余风险
_(待填写)_

---

## 🔍 集中检查 #2（Task 4-6 完成后的终审 Debug 循环）

- 总体跑 `pytest tests/ -v`，确保 0 fail
- 代码质量复查：无死代码、调试残留
- 安全检查：无敏感信息泄露
- commit 历史清晰，message 关联 task 编号
- 回看 `input.md` 确认需求完全满足

### 检查结论
_(待填写)_

### 发现的问题
_(待填写)_
