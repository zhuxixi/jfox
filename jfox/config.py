"""配置管理"""

import os
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import yaml
from rich.console import Console

_console = Console(stderr=True)


def get_default_kb_path() -> Path:
    """获取默认知识库路径（从全局配置）"""
    try:
        from .global_config import get_global_config_manager

        return get_global_config_manager().get_default_kb_path()
    except Exception:
        return Path.home() / ".zettelkasten" / "default"


@dataclass
class ZKConfig:
    """Zettelkasten 配置"""

    # 路径
    base_dir: Path = field(default_factory=get_default_kb_path)
    notes_dir: Path = field(init=False)
    zk_dir: Path = field(init=False)
    chroma_dir: Path = field(init=False)

    # Embedding 配置
    embedding_model: str = "auto"  # auto = 根据 device 自动选择模型
    embedding_dimension: int = 0  # 0 = 动态，由模型决定
    device: str = "auto"  # auto / cuda / cpu
    batch_size: int = 32

    # 检索配置
    default_semantic_top: int = 5
    default_graph_hops: int = 2
    similarity_threshold: float = 0.7

    # 同步配置
    auto_sync: bool = True
    sync_interval: int = 30  # 秒

    def __post_init__(self):
        self.notes_dir = self.base_dir / "notes"
        self.zk_dir = self.base_dir / ".zk"
        self.chroma_dir = self.zk_dir / "chroma_db"

    def ensure_dirs(self):
        """确保目录存在"""
        dirs = [
            self.notes_dir / "fleeting",
            self.notes_dir / "literature",
            self.notes_dir / "permanent",
            self.zk_dir,
            self.chroma_dir,
            self.zk_dir / "cache",
        ]
        for d in dirs:
            d.mkdir(parents=True, exist_ok=True)

    def save(self, path: Optional[Path] = None):
        """保存配置到文件"""
        if path is None:
            path = self.zk_dir / "config.yaml"

        config_dict = {
            "base_dir": str(self.base_dir),
            "embedding_model": self.embedding_model,
            "embedding_dimension": self.embedding_dimension,
            "device": self.device,
            "batch_size": self.batch_size,
            "default_semantic_top": self.default_semantic_top,
            "default_graph_hops": self.default_graph_hops,
            "similarity_threshold": self.similarity_threshold,
            "auto_sync": self.auto_sync,
            "sync_interval": self.sync_interval,
        }

        with open(path, "w", encoding="utf-8") as f:
            yaml.dump(config_dict, f, allow_unicode=True, sort_keys=False)

    @classmethod
    def load(cls, path: Optional[Path] = None) -> "ZKConfig":
        """从文件加载配置"""
        # 首先获取默认知识库路径
        default_path = get_default_kb_path()

        if path is None:
            path = default_path / ".zk" / "config.yaml"

        if not path.exists():
            return cls(base_dir=default_path)

        with open(path, "r", encoding="utf-8") as f:
            config_dict = yaml.safe_load(f)

        # 转换路径
        if "base_dir" in config_dict:
            config_dict["base_dir"] = Path(config_dict["base_dir"])
        else:
            config_dict["base_dir"] = default_path

        return cls(**config_dict)

    @classmethod
    def for_kb(cls, kb_path: Path) -> "ZKConfig":
        """为指定知识库创建配置"""
        return cls(base_dir=kb_path)


# 全局配置实例（动态获取当前默认知识库）
def get_config() -> ZKConfig:
    """获取当前默认知识库的配置"""
    return ZKConfig.load()


# 为了向后兼容，保留 config 变量，但使用动态获取
config = get_config()


def _reset_singletons():
    """重置所有缓存的单例（搜索引擎、向量存储、BM25 索引、embedding 后端）"""
    import importlib

    for module_name, fn_name in [
        (".bm25_index", "reset_bm25_index"),
        (".search_engine", "reset_search_engine"),
        (".vector_store", "reset_vector_store"),
        (".embedding_backend", "reset_backend"),
    ]:
        try:
            module = importlib.import_module(module_name, package="jfox")
            getattr(module, fn_name)()
        except Exception:
            pass


@contextmanager
def use_kb(kb_name: Optional[str] = None):
    """
    临时使用指定知识库的上下文管理器

    用法:
        with use_kb("work"):
            # 在这个上下文中，操作都在 work 知识库上
            note = create_note(...)

    优先级: --kb > JFOX_KB > 全局配置 default
    当 kb_name 为 None 时，会先检查 JFOX_KB 环境变量，
    若未设置则使用全局配置中的默认知识库。

    Args:
        kb_name: 知识库名称，None 表示使用当前默认知识库

    Raises:
        ValueError: 知识库不存在
    """
    resolved_from_env = False

    if not kb_name:
        env_kb = os.environ.get("JFOX_KB", "").strip()
        if env_kb:
            kb_name = env_kb
            resolved_from_env = True
        else:
            yield
            return

    from .kb_manager import get_kb_manager

    manager = get_kb_manager()

    if not manager.config_manager.kb_exists(kb_name):
        raise ValueError(f"Knowledge base '{kb_name}' not found")

    # 保存原始配置
    original_base_dir = config.base_dir
    original_notes_dir = config.notes_dir
    original_zk_dir = config.zk_dir
    original_chroma_dir = config.chroma_dir

    try:
        # 切换到目标知识库
        kb_path = manager.config_manager.get_kb_path(kb_name)
        config.base_dir = kb_path
        config.notes_dir = kb_path / "notes"
        config.zk_dir = kb_path / ".zk"
        config.chroma_dir = config.zk_dir / "chroma_db"

        # 重置索引和搜索引擎（使用新的知识库路径）
        _reset_singletons()

        if resolved_from_env:
            _console.print(
                f"Using knowledge base '{kb_name}' (from JFOX_KB environment variable)",
                style="dim",
            )

        yield
    finally:
        # 恢复原始配置
        config.base_dir = original_base_dir
        config.notes_dir = original_notes_dir
        config.zk_dir = original_zk_dir
        config.chroma_dir = original_chroma_dir

        # 重置单例，下次访问会用恢复后的配置重建
        _reset_singletons()
