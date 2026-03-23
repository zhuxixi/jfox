"""
pytest 配置和 fixtures
"""

import pytest
from pathlib import Path

# 添加项目根目录到路径
import sys
sys.path.insert(0, str(Path(__file__).parent.parent))


from tests.utils.temp_kb import temp_knowledge_base, TemporaryKnowledgeBase
from tests.utils.zk_cli import ZKCLI
from tests.utils.note_generator import NoteGenerator, generate_test_dataset


@pytest.fixture
def temp_kb():
    """
    提供临时知识库的 fixture
    
    用法:
        def test_something(temp_kb):
            cli = ZKCLI(temp_kb)
            cli.init()
            # 测试代码...
    """
    with temp_knowledge_base() as kb_path:
        yield kb_path


@pytest.fixture
def cli(temp_kb):
    """
    提供已初始化的 CLI 实例
    
    用法:
        def test_something(cli):
            result = cli.add("内容", title="测试")
            assert result.success
    """
    zk_cli = ZKCLI(temp_kb)
    zk_cli.init()
    yield zk_cli
    # 测试结束后清理
    zk_cli.cleanup()


@pytest.fixture
def generator():
    """
    提供笔记生成器
    
    用法:
        def test_bulk(generator):
            notes = generator.generate(100, NoteType.PERMANENT)
            # 测试代码...
    """
    return NoteGenerator(seed=42)


@pytest.fixture
def small_dataset():
    """提供小型测试数据集（50条）"""
    return generate_test_dataset("small")


@pytest.fixture
def medium_dataset():
    """提供中型测试数据集（200条）"""
    return generate_test_dataset("medium")


@pytest.fixture(scope="session")
def large_dataset():
    """提供大型测试数据集（1000条）- 会话级别缓存"""
    return generate_test_dataset("large")


# pytest 配置
def pytest_configure(config):
    """配置 pytest"""
    config.addinivalue_line(
        "markers", "slow: marks tests as slow (deselect with '-m \"not slow\"')"
    )
    config.addinivalue_line(
        "markers", "performance: marks tests as performance tests"
    )
    config.addinivalue_line(
        "markers", "integration: marks tests as integration tests"
    )
    config.addinivalue_line(
        "markers", "timeout(seconds): marks tests with timeout in seconds"
    )


def pytest_addoption(parser):
    """添加命令行选项"""
    parser.addoption(
        "--keep-data",
        action="store_true",
        default=False,
        help="Keep test data after tests finish (for debugging)"
    )
    parser.addoption(
        "--benchmark",
        action="store_true",
        default=False,
        help="Run performance benchmarks"
    )
