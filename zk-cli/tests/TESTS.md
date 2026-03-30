# JFox 测试规范

> 本文档定义 JFox 项目的测试组织结构、命名规范和执行标准。

## 目录结构

```
tests/
├── TESTS.md                 # 本文档
├── conftest.py              # pytest 全局配置和 fixtures
├── unit/                    # 单元测试目录
│   ├── __init__.py
│   ├── test_formatters.py
│   ├── test_models.py
│   ├── test_bm25_index.py
│   ├── test_config.py
│   ├── test_global_config.py
│   ├── test_kb_manager.py
│   ├── test_template.py
│   ├── test_template_cli.py
│   └── test_graph.py
├── integration/             # 集成测试目录
│   ├── __init__.py
│   ├── test_backlinks.py
│   ├── test_hybrid_search.py
│   ├── test_kb_workflow.py
│   ├── test_suggest_links.py
│   ├── test_core_workflow.py
│   ├── test_advanced_features.py
│   └── test_cli_format.py
├── performance/             # 性能测试目录
│   ├── __init__.py
│   └── test_performance.py
└── utils/                   # 测试工具
    ├── __init__.py
    ├── temp_kb.py
    ├── zk_cli.py
    └── note_generator.py
```

## 测试类型定义

### 单元测试 (Unit Tests)

- **定义**: 测试单个函数/类，不依赖外部服务
- **特点**: 快速、独立、可并行
- **依赖**: 仅使用 mock 和临时文件
- **执行时间**: < 1秒
- **目录**: `tests/unit/`

### 集成测试 (Integration Tests)

- **定义**: 测试多个模块协作，依赖真实服务
- **特点**: 验证完整工作流程
- **依赖**: 数据库、文件系统、向量模型等
- **执行时间**: 10-60秒
- **目录**: `tests/integration/`

### 性能测试 (Performance Tests)

- **定义**: 测试性能指标和基准
- **特点**: 测量执行时间和资源消耗
- **依赖**: 与集成测试类似
- **执行时间**: 可变，需单独运行
- **目录**: `tests/performance/`

## 命名规范

### 文件命名

| 测试类型 | 命名格式 | 示例 |
|----------|----------|------|
| 单元测试 | `test_{模块名}.py` | `test_formatters.py` |
| 集成测试 | `test_{功能}_integration.py` | `test_kb_workflow_integration.py` |
| 性能测试 | `test_{模块}_performance.py` | `test_search_performance.py` |

### 类命名

| 测试类型 | 命名格式 | 示例 |
|----------|----------|------|
| 单元测试 | `Test{模块}Unit` | `TestFormattersUnit` |
| 集成测试 | `Test{功能}Integration` | `TestKBWorkflowIntegration` |
| 性能测试 | `Test{模块}Performance` | `TestSearchPerformance` |

### 方法命名

```python
# 单元测试 - 明确测试场景和预期
def test_{场景}_{预期结果}(self):
    """测试 {场景} 时应该 {预期结果}"""
    pass

# 集成测试 - 描述完整场景
def test_{完整操作场景}(self):
    """测试 {完整场景描述}"""
    pass

# 性能测试 - 明确操作和指标
def test_{操作}_performance(self):
    """测试 {操作} 性能 - 目标: {指标}"""
    pass
```

## pytest 标记

### 必需标记

所有测试必须添加以下标记之一：

```python
@pytest.mark.unit           # 单元测试
@pytest.mark.integration    # 集成测试
@pytest.mark.performance    # 性能测试
```

### 耗时标记

根据执行时间添加：

```python
@pytest.mark.fast           # < 1秒
@pytest.mark.normal         # 1-10秒
@pytest.mark.slow           # 10-60秒
@pytest.mark.very_slow      # > 60秒
```

### 其他标记

```python
@pytest.mark.skip           # 跳过测试
@pytest.mark.skipif         # 条件跳过
@pytest.mark.xfail          # 预期失败
@pytest.mark.parametrize    # 参数化测试
```

## 测试创建模板

### 单元测试模板

```python
# tests/unit/test_example.py
"""
测试类型: 单元测试
目标模块: zk.example
预估耗时: < 1秒
依赖要求: 无外部依赖，使用 mock

创建检查清单:
- [x] 文件放在 tests/unit/ 目录
- [x] 添加了 @pytest.mark.unit 标记
- [x] 添加了 @pytest.mark.fast 标记
- [x] 预估耗时已记录
"""

import pytest
from unittest.mock import Mock, patch


@pytest.mark.unit
@pytest.mark.fast
class TestExampleUnit:
    """测试 example 模块 - 预估耗时: < 1秒"""
    
    def test_function_with_valid_input_returns_expected(self):
        """测试函数接收有效输入时返回预期结果"""
        # Arrange
        input_data = "test"
        
        # Act
        result = example_function(input_data)
        
        # Assert
        assert result == "expected"
    
    def test_function_with_invalid_input_raises_error(self):
        """测试函数接收无效输入时抛出异常"""
        with pytest.raises(ValueError):
            example_function(None)
```

### 集成测试模板

```python
# tests/integration/test_example_integration.py
"""
测试类型: 集成测试
目标功能: 完整工作流
预估耗时: 10-30秒
依赖要求: 需要临时知识库，真实文件系统

创建检查清单:
- [x] 文件放在 tests/integration/ 目录
- [x] 添加了 @pytest.mark.integration 标记
- [x] 添加了 @pytest.mark.slow 标记
- [x] 预估耗时已记录
"""

import pytest


@pytest.mark.integration
@pytest.mark.slow
class TestExampleWorkflowIntegration:
    """测试 example 工作流 - 预估耗时: 10-30秒"""
    
    def test_complete_workflow_from_start_to_finish(self, temp_kb):
        """测试从开始到结束的完整工作流"""
        # 测试完整流程...
        pass
```

## 运行命令

### 快速运行（开发常用）

```bash
# 只运行单元测试
pytest tests/unit/ -v

# 运行快速测试（< 1秒）
pytest tests/ -m "fast" -v

# 排除慢测试
pytest tests/ -m "not slow and not very_slow" -v
```

### 完整运行

```bash
# 运行所有测试
pytest tests/ -v

# 运行单元测试 + 集成测试
pytest tests/unit tests/integration -v

# 运行性能测试
pytest tests/performance/ -v
```

### CI/CD 分级运行

```bash
# PR 检查 - 快速反馈
pytest tests/unit/ -v --cov=zk

# 合并前检查 - 完整测试
pytest tests/ -m "not very_slow" -v --cov=zk

# 每日/发布前 - 全量测试
pytest tests/ -v --cov=zk --cov-report=html
```

## 测试编写最佳实践

### 1. 单一职责

每个测试只验证一个概念：

```python
# ✅ 好的做法
def test_create_note_with_valid_data_succeeds(self):
    """测试使用有效数据创建笔记成功"""
    pass

def test_create_note_with_empty_title_raises_error(self):
    """测试使用空标题创建笔记抛出错误"""
    pass

# ❌ 避免
def test_create_note(self):
    """测试创建笔记（测试太多内容）"""
    pass
```

### 2. 清晰的三段式结构

```python
def test_example(self):
    """测试示例"""
    # Arrange - 准备
    input_data = prepare_test_data()
    
    # Act - 执行
    result = function_under_test(input_data)
    
    # Assert - 验证
    assert result == expected_value
```

### 3. 使用 Fixtures

```python
# conftest.py 中定义
@pytest.fixture
def temp_kb(tmp_path):
    """创建临时知识库"""
    # 创建逻辑...
    yield kb_path
    # 清理逻辑...

# 测试中使用
def test_with_kb(self, temp_kb):
    """使用临时知识库进行测试"""
    pass
```

### 4. 避免测试依赖

```python
# ❌ 避免 - 测试间有依赖
def test_first(self):
    self.shared_data = create_data()

def test_second(self):
    use(self.shared_data)  # 依赖 test_first

# ✅ 好的做法 - 每个测试独立
def test_first(self):
    data = create_data()
    # 测试...

def test_second(self):
    data = create_data()  # 自己创建所需数据
    # 测试...
```

## 性能基准

在 Intel Core Ultra 7 258V 上的参考指标：

| 测试类型 | 目标执行时间 | 最大执行时间 |
|----------|--------------|--------------|
| 单元测试 | < 100ms | < 1s |
| 快速集成测试 | 1-5s | < 10s |
| 慢速集成测试 | 10-30s | < 60s |
| 性能测试 | 按场景定义 | 按场景定义 |

## 参考

- [pytest 文档](https://docs.pytest.org/)
- [Python 测试最佳实践](https://testing.googleblog.com/)
- [项目 AGENTS.md](../../AGENTS.md)
