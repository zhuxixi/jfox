# 测试结构迁移说明

> Issue #44: 测试规范实施状态

## 已完成工作

### ✅ 1. 测试规范文档 (TESTS.md)

创建了完整的测试规范文档，包含：
- 目录结构规范
- 测试类型定义（单元测试、集成测试、性能测试）
- 命名规范（文件、类、方法）
- pytest 标记规范
- 测试创建模板
- 运行命令参考

### ✅ 2. 目录结构

创建了新的目录结构：
```
tests/
├── unit/              # 单元测试（快速、独立）
├── integration/       # 集成测试（多组件协作）
├── performance/       # 性能测试（基准测试）
└── utils/             # 测试工具
```

### ✅ 3. pytest 配置更新 (conftest.py)

添加了新的测试标记：
- `unit` - 单元测试标记
- `integration` - 集成测试标记
- `performance` - 性能测试标记
- `fast/normal/slow/very_slow` - 耗时分级标记

自动标记逻辑：根据测试文件路径自动添加类型标记。

### ✅ 4. 单元测试迁移

已迁移并标记的单元测试（全部通过 ✅）：

| 源文件 | 目标位置 | 状态 |
|--------|----------|------|
| `test_global_config_unit.py` | `unit/test_global_config.py` | ✅ 通过 |
| `test_kb_manager_unit.py` | `unit/test_kb_manager.py` | ✅ 通过 |
| `test_template_cli_unit.py` | `unit/test_template_cli.py` | ✅ 通过 |
| `test_formatters.py` | `unit/test_formatters.py` | ✅ 通过 |
| `test_template.py` | `unit/test_template.py` | ✅ 通过 |

**单元测试结果**: 140 个测试全部通过，耗时 0.60s

## 待完成工作

### ⏳ 1. 集成测试迁移

以下集成测试文件因编码问题（UTF-8/GBK 混合）暂时保留在原位置：
- `test_backlinks.py`
- `test_advanced_features.py`
- `test_hybrid_search.py`
- `test_integration.py`
- `test_suggest_links.py`
- `test_cli_format.py`
- `test_core_workflow.py`

**建议处理方式**:
1. 未来逐步重写这些测试，使用新的目录结构
2. 或者一次性批量转换编码格式

### ⏳ 2. 性能测试迁移

- `test_performance_unit.py` 已迁移到 `performance/test_performance.py`
- 但因编码问题可能需要重新保存

## 使用新的测试结构

### 运行单元测试（快速）

```bash
pytest tests/unit/ -v
```

### 运行集成测试

```bash
pytest tests/integration/ -v
```

### 按标记运行

```bash
# 只运行快速测试
pytest tests/ -m "fast" -v

# 排除慢测试
pytest tests/ -m "not slow" -v

# 运行单元测试
pytest tests/ -m "unit" -v
```

## 创建新测试的规范

### 单元测试模板

```python
# tests/unit/test_example.py
"""
测试类型: 单元测试
目标模块: zk.example
预估耗时: < 1秒
依赖要求: 无外部依赖，使用 mock
"""
import pytest

pytestmark = [pytest.mark.unit, pytest.mark.fast]


class TestExampleUnit:
    """测试 example 模块 - 预估耗时: < 1秒"""
    
    def test_function_with_valid_input_returns_expected(self):
        """测试函数接收有效输入时返回预期结果"""
        pass
```

### 集成测试模板

```python
# tests/integration/test_example_integration.py
"""
测试类型: 集成测试
目标功能: 完整工作流
预估耗时: 10-30秒
依赖要求: 需要临时知识库
"""
import pytest

pytestmark = [pytest.mark.integration, pytest.mark.slow]


class TestExampleWorkflowIntegration:
    """测试 example 工作流 - 预估耗时: 10-30秒"""
    
    def test_complete_workflow_from_start_to_finish(self, temp_kb):
        """测试从开始到结束的完整工作流"""
        pass
```

## 遗留文件处理建议

### 方案 1: 渐进式迁移（推荐）

1. 新测试严格按照 TESTS.md 规范创建
2. 旧测试在修改时逐步迁移到新目录
3. 保持向后兼容，原有测试继续运行

### 方案 2: 一次性迁移

1. 批量转换编码格式（UTF-8）
2. 一次性移动所有文件到新目录
3. 添加 pytest 标记

## 当前测试运行状态

```bash
# 原有测试（全部）
pytest tests/test_*.py -v

# 新的单元测试（快速）
pytest tests/unit/ -v          # 140 passed in 0.60s
```
