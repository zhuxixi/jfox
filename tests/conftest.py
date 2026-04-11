"""
pytest 配置和 fixtures

提供：
1. 临时知识库 fixture
2. CLI 封装 fixture
3. 笔记生成器 fixture
4. 模型缓存（session 级别）
5. Mock embedding 支持（快速测试）
"""

import os
import shutil
import sys
import tempfile
from pathlib import Path

# 添加项目根目录到路径
sys.path.insert(0, str(Path(__file__).parent.parent))

# 在导入 zk 模块之前设置测试 KB 根目录
# 这样 DEFAULT_KB_PATH 会指向临时目录，路径验证在测试中自然通过
_TEST_ROOT = Path(tempfile.mkdtemp(prefix="zk_test_root_"))
os.environ["ZK_KB_ROOT"] = str(_TEST_ROOT)

import pytest

# ============================================================================
# 模型缓存 - Session 级别（大幅减少重复加载）
# ============================================================================


@pytest.fixture(scope="session")
def embedding_model():
    """
    Session 级别的模型缓存

    所有测试共享一个模型实例，避免重复加载（节省 30-60 秒/测试）
    """
    # 使用环境变量控制是否使用真实模型
    if os.environ.get("ZK_TEST_MOCK_EMBEDDING", "0") == "1":
        # 返回 mock 模型
        return None

    try:
        from sentence_transformers import SentenceTransformer

        model = SentenceTransformer("sentence-transformers/all-MiniLM-L6-v2")
        return model
    except Exception as e:
        print(f"Warning: Failed to load embedding model: {e}")
        return None


@pytest.fixture(scope="session")
def mock_embedding_backend():
    """
    Mock embedding backend 用于快速测试

    返回随机向量，不加载真实模型，测试速度快 10-20 倍
    """
    import numpy as np

    class MockEmbeddingBackend:
        """Mock embedding backend - 返回随机向量"""

        def __init__(self):
            self.dimension = 384

        def encode(self, texts, **kwargs):
            """返回随机向量"""
            if isinstance(texts, str):
                texts = [texts]
            return np.random.rand(len(texts), self.dimension).astype("float32")

        def encode_batch(self, texts, batch_size=32):
            """批量编码"""
            return self.encode(texts)

    return MockEmbeddingBackend()


# ============================================================================
# 知识库和 CLI Fixtures
# ============================================================================

# 从 utils 目录导入（pytest 自动将 tests 目录加入路径）
from utils.jfox_cli import ZKCLI
from utils.note_generator import NoteGenerator, generate_test_dataset
from utils.temp_kb import temp_knowledge_base


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
def cli_fast(temp_kb, mock_embedding_backend):
    """
    使用 mock embedding 的快速 CLI 实例

    用于不需要真实语义搜索的测试，速度快 10-20 倍

    用法:
        @pytest.mark.fast
        def test_something(cli_fast):
            result = cli_fast.add("内容", title="测试")
            assert result.success
    """
    # 使用 mock backend
    import unittest.mock

    from jfox import embedding_backend

    def mock_get_backend():
        return mock_embedding_backend

    with unittest.mock.patch.object(embedding_backend, "get_backend", mock_get_backend):
        zk_cli = ZKCLI(temp_kb)
        zk_cli.init()
        yield zk_cli
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


# ============================================================================
# pytest 配置
# ============================================================================


def pytest_configure(config):
    """配置 pytest 标记"""
    # 测试类型标记
    config.addinivalue_line("markers", "unit: marks tests as unit tests (fast, isolated)")
    config.addinivalue_line(
        "markers", "integration: marks tests as integration tests (tests multiple components)"
    )
    config.addinivalue_line("markers", "performance: marks tests as performance tests")
    config.addinivalue_line("markers", "e2e: marks tests as end-to-end tests")

    # 耗时分级标记
    config.addinivalue_line("markers", "fast: marks tests as fast (< 1 second)")
    config.addinivalue_line("markers", "normal: marks tests as normal speed (1-10 seconds)")
    config.addinivalue_line("markers", "slow: marks tests as slow (10-60 seconds)")
    config.addinivalue_line("markers", "very_slow: marks tests as very slow (> 60 seconds)")

    # 功能标记（保留原有标记兼容）
    config.addinivalue_line("markers", "workflow: marks tests as workflow tests")
    config.addinivalue_line("markers", "bulk: marks tests that import large amount of data (slow)")
    config.addinivalue_line(
        "markers", "embedding: marks tests that require real embedding model (very slow)"
    )


def pytest_addoption(parser):
    """添加命令行选项"""
    parser.addoption(
        "--keep-data",
        action="store_true",
        default=False,
        help="Keep test data after tests finish (for debugging)",
    )
    parser.addoption(
        "--benchmark", action="store_true", default=False, help="Run performance benchmarks"
    )


def pytest_collection_modifyitems(config, items):
    """
    自动标记测试

    根据测试路径和名称自动添加标记，方便筛选
    """
    for item in items:
        nodeid = item.nodeid.lower()

        # 根据路径自动添加测试类型标记
        if "/unit/" in nodeid or "\\unit\\" in nodeid:
            if "unit" not in item.keywords:
                item.add_marker(pytest.mark.unit)
        elif "/integration/" in nodeid or "\\integration\\" in nodeid:
            if "integration" not in item.keywords:
                item.add_marker(pytest.mark.integration)
        elif "/performance/" in nodeid or "\\performance\\" in nodeid:
            if "performance" not in item.keywords:
                item.add_marker(pytest.mark.performance)

        # 如果测试名称包含 'embedding' 或 'semantic'，自动添加 embedding 和 very_slow 标记
        if any(keyword in nodeid for keyword in ["embedding", "semantic", "vector"]):
            if "embedding" not in item.keywords:
                item.add_marker(pytest.mark.embedding)
            if "very_slow" not in item.keywords:
                item.add_marker(pytest.mark.very_slow)

        # 如果测试名称包含 'search' 或 'suggest'，自动添加 slow 标记
        if any(keyword in nodeid for keyword in ["search", "suggest", "query"]):
            if "slow" not in item.keywords and "very_slow" not in item.keywords:
                item.add_marker(pytest.mark.slow)

        # 如果测试名称包含 'bulk' 或 'batch'，自动添加 slow 和 bulk 标记
        if any(keyword in nodeid for keyword in ["bulk", "batch", "large", "many"]):
            if "slow" not in item.keywords:
                item.add_marker(pytest.mark.slow)
            if "bulk" not in item.keywords:
                item.add_marker(pytest.mark.bulk)


@pytest.fixture(scope="session", autouse=True)
def _cleanup_test_root():
    """会话结束时清理测试 KB 根目录"""
    yield
    test_root = Path(os.environ.get("ZK_KB_ROOT", ""))
    if test_root.exists() and "zk_test" in test_root.name:
        shutil.rmtree(test_root, ignore_errors=True)
