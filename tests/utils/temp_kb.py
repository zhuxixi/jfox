"""
临时知识库管理

提供测试用的隔离知识库环境
"""

import shutil
import uuid
from contextlib import contextmanager
from pathlib import Path
from typing import Generator, Optional

from jfox.global_config import DEFAULT_KB_PATH
from jfox.kb_manager import get_kb_manager


@contextmanager
def temp_knowledge_base(prefix: str = "zk_test_") -> Generator[Path, None, None]:
    """
    创建临时知识库用于测试

    KB 目录创建在测试根目录（ZK_KB_ROOT）下，
    确保 CLI 路径验证可以通过。

    用法:
        with temp_knowledge_base() as kb_path:
            # 在 kb_path 中进行测试
            pass
        # 测试结束后自动清理

    Args:
        prefix: 临时目录前缀

    Yields:
        知识库路径
    """
    test_dir = DEFAULT_KB_PATH / f"{prefix}{uuid.uuid4().hex[:8]}"
    kb_path = test_dir / "kb"

    try:
        yield kb_path
    finally:
        # 清理临时目录
        if test_dir.exists():
            shutil.rmtree(test_dir)


@contextmanager
def temp_kb_registered(name: Optional[str] = None) -> Generator[str, None, None]:
    """
    创建临时知识库并注册到全局配置

    KB 创建在测试根目录（ZK_KB_ROOT）下。

    用法:
        with temp_kb_registered("test_kb") as kb_name:
            # 使用 kb_name 进行测试
            pass
        # 测试结束后自动注销和清理

    Args:
        name: 知识库名称（默认生成随机名称）

    Yields:
        知识库名称
    """
    kb_name = name or f"test_{uuid.uuid4().hex[:8]}"
    kb_path = DEFAULT_KB_PATH / kb_name

    manager = get_kb_manager()

    try:
        # 创建并注册知识库
        success, _ = manager.create(
            name=kb_name,
            path=kb_path,
            description=f"Temporary KB for testing: {kb_name}",
            set_as_default=False,
        )

        if not success:
            raise RuntimeError(f"Failed to create temp KB: {kb_name}")

        yield kb_name

    finally:
        # 注销并清理
        try:
            manager.remove(kb_name, delete_data=True)
        except Exception:
            pass


class TemporaryKnowledgeBase:
    """
    临时知识库类（用于需要更多控制的场景）

    KB 目录创建在测试根目录（ZK_KB_ROOT）下。

    用法:
        kb = TemporaryKnowledgeBase()
        kb.create()
        try:
            # 使用 kb.path 进行测试
            pass
        finally:
            kb.cleanup()
    """

    def __init__(self, prefix: str = "zk_test_"):
        self.prefix = prefix
        self.temp_dir: Optional[Path] = None
        self.path: Optional[Path] = None

    def create(self) -> Path:
        """创建临时知识库"""
        self.temp_dir = DEFAULT_KB_PATH / f"{self.prefix}{uuid.uuid4().hex[:8]}"
        self.path = self.temp_dir / "kb"

        # 初始化知识库结构
        from jfox.config import ZKConfig

        config = ZKConfig(base_dir=self.path)
        config.ensure_dirs()

        return self.path

    def cleanup(self):
        """清理临时知识库"""
        if self.temp_dir and self.temp_dir.exists():
            shutil.rmtree(self.temp_dir)
        self.temp_dir = None
        self.path = None

    def __enter__(self) -> Path:
        return self.create()

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.cleanup()
        return False
