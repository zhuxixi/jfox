"""
性能优化模块

提供模型缓存、批量处理等优化功能
"""

import logging
import time
from functools import wraps
from typing import Any, Callable, List, Optional

logger = logging.getLogger(__name__)


# =============================================================================
# 性能计时装饰器
# =============================================================================


def timer(func: Callable) -> Callable:
    """计时装饰器"""

    @wraps(func)
    def wrapper(*args, **kwargs):
        start = time.time()
        result = func(*args, **kwargs)
        elapsed = time.time() - start
        logger.info(f"{func.__name__} took {elapsed:.2f}s")
        return result

    return wrapper


# =============================================================================
# 批量处理优化
# =============================================================================


class BatchProcessor:
    """
    批量处理器

    优化大批量数据的处理性能
    """

    def __init__(self, batch_size: int = 32):
        self.batch_size = batch_size

    def process(
        self, items: List[Any], processor: Callable[[Any], Any], show_progress: bool = True
    ) -> List[Any]:
        """
        批量处理项目

        Args:
            items: 待处理项目列表
            processor: 处理函数
            show_progress: 是否显示进度

        Returns:
            处理结果列表
        """
        results = []
        total = len(items)

        if show_progress:
            from rich.progress import Progress, SpinnerColumn, TextColumn

            progress = Progress(
                SpinnerColumn(),
                TextColumn("[progress.description]{task.description}"),
            )
            task = progress.add_task(f"Processing {total} items...", total=total)
        else:
            progress = None
            task = None

        try:
            if progress:
                progress.start()

            for i, item in enumerate(items):
                try:
                    result = processor(item)
                    results.append(result)
                except Exception as e:
                    logger.warning(f"Failed to process item {i}: {e}")

                if progress and task is not None:
                    progress.update(task, advance=1)

            if progress:
                progress.stop()

        except Exception:
            if progress:
                progress.stop()
            raise

        return results

    def process_embeddings(
        self, texts: List[str], backend, show_progress: bool = True
    ) -> List[List[float]]:
        """
        批量处理文本嵌入

        Args:
            texts: 文本列表
            backend: EmbeddingBackend 实例
            show_progress: 是否显示进度

        Returns:
            嵌入向量列表
        """
        results = []
        total = len(texts)

        if show_progress:
            from rich.progress import Progress, SpinnerColumn, TextColumn

            progress = Progress(
                SpinnerColumn(),
                TextColumn("[progress.description]{task.description}"),
            )
            task = progress.add_task(f"Encoding {total} texts...", total=total)
            progress.start()
        else:
            progress = None
            task = None

        try:
            # 分批处理
            for i in range(0, len(texts), self.batch_size):
                batch = texts[i : i + self.batch_size]

                try:
                    # 批量编码
                    embeddings = backend.encode(batch)
                    results.extend(embeddings.tolist())
                except Exception as e:
                    logger.warning(f"Failed to encode batch {i}: {e}")
                    # 失败时返回零向量
                    dim = backend.model.get_sentence_embedding_dimension()
                    results.extend([[0.0] * dim] * len(batch))

                if progress and task is not None:
                    progress.update(task, advance=len(batch))

            if progress:
                progress.stop()

        except Exception:
            if progress:
                progress.stop()
            raise

        return results


# =============================================================================
# 快速批量导入
# =============================================================================


@timer
def bulk_import_notes(
    notes_data: List[dict],
    note_type: str = "permanent",
    batch_size: int = 32,
    show_progress: bool = True,
) -> dict:
    """
    快速批量导入笔记

    优化后的批量导入，使用批量嵌入和批量数据库操作

    Args:
        notes_data: 笔记数据列表 [{"title": ..., "content": ...}]
        note_type: 笔记类型
        batch_size: 批大小
        show_progress: 是否显示进度

    Returns:
        导入统计
    """
    from . import note as note_module
    from .bm25_index import get_bm25_index
    from .embedding_backend import get_backend
    from .models import NoteType
    from .vector_store import get_vector_store

    nt = NoteType(note_type.lower())
    backend = get_backend()
    vector_store = get_vector_store()

    # 确保模型已加载
    if backend.model is None:
        backend.load()

    imported = 0
    failed = 0

    if show_progress:
        from rich.progress import Progress, SpinnerColumn, TextColumn

        progress = Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
        )
        task = progress.add_task(f"Importing {len(notes_data)} notes...", total=len(notes_data))
        progress.start()
    else:
        progress = None
        task = None

    try:
        # 分批处理
        for i in range(0, len(notes_data), batch_size):
            batch = notes_data[i : i + batch_size]

            # 创建笔记对象
            notes = []
            for data in batch:
                try:
                    note = note_module.create_note(
                        content=data.get("content", ""),
                        title=data.get("title"),
                        note_type=nt,
                        tags=data.get("tags", []),
                    )
                    notes.append(note)
                except Exception as e:
                    logger.warning(f"Failed to create note: {e}")
                    failed += 1

            # 批量保存（不索引）
            for note in notes:
                try:
                    note.filepath.parent.mkdir(parents=True, exist_ok=True)
                    with open(note.filepath, "w", encoding="utf-8") as f:
                        f.write(note.to_markdown())
                    imported += 1
                except Exception as e:
                    logger.warning(f"Failed to save note: {e}")
                    failed += 1

            # 批量索引
            try:
                # 准备批量数据
                documents = [f"{n.title}\n{n.content}" for n in notes]
                embeddings = backend.encode(documents).tolist()

                # 批量添加到 ChromaDB
                ids = [n.id for n in notes]
                metadatas = [
                    {
                        "title": n.title,
                        "type": n.type.value,
                        "filepath": str(n.filepath),
                        "tags": ",".join(n.tags),
                    }
                    for n in notes
                ]

                vector_store.collection.add(
                    ids=ids, documents=documents, embeddings=embeddings, metadatas=metadatas
                )

                # 批量添加到 BM25 索引
                bm25 = get_bm25_index()
                bm25_docs = [(n.id, f"{n.title} {n.content}") for n in notes]
                bm25.add_documents_batch(bm25_docs)

            except Exception as e:
                logger.warning(f"Failed to index batch: {e}")

            if progress and task is not None:
                progress.update(task, advance=len(batch))

        if progress:
            progress.stop()

    except Exception:
        if progress:
            progress.stop()
        raise

    return {
        "imported": imported,
        "failed": failed,
        "total": len(notes_data),
    }


# =============================================================================
# 缓存管理
# =============================================================================


class ModelCache:
    """
    模型缓存管理

    管理 embedding 模型的缓存，避免重复加载
    """

    _instance: Optional[Any] = None
    _last_used: Optional[float] = None
    _ttl: float = 300  # 5 分钟 TTL

    @classmethod
    def get_model(cls, model_name: str = "sentence-transformers/all-MiniLM-L6-v2"):
        """
        获取缓存的模型

        Args:
            model_name: 模型名称

        Returns:
            模型实例
        """
        from sentence_transformers import SentenceTransformer

        now = time.time()

        # 检查缓存是否有效
        if cls._instance is not None:
            if cls._last_used and (now - cls._last_used) < cls._ttl:
                cls._last_used = now
                logger.debug("Using cached model")
                return cls._instance

        # 加载新模型
        logger.info(f"Loading model: {model_name}")
        cls._instance = SentenceTransformer(model_name)
        cls._last_used = now

        return cls._instance

    @classmethod
    def clear(cls):
        """清除缓存"""
        cls._instance = None
        cls._last_used = None
        logger.info("Model cache cleared")


# =============================================================================
# 性能监控
# =============================================================================


class PerformanceMonitor:
    """
    性能监控器

    监控和报告操作性能
    """

    def __init__(self):
        self.metrics = {}

    def record(self, operation: str, duration: float):
        """记录操作耗时"""
        if operation not in self.metrics:
            self.metrics[operation] = []
        self.metrics[operation].append(duration)

    def report(self) -> dict:
        """生成性能报告"""
        report = {}
        for op, times in self.metrics.items():
            report[op] = {
                "count": len(times),
                "total": sum(times),
                "avg": sum(times) / len(times),
                "min": min(times),
                "max": max(times),
            }
        return report

    def print_report(self):
        """打印性能报告"""
        from rich.console import Console
        from rich.table import Table

        report = self.report()
        console = Console()

        table = Table(title="Performance Report")
        table.add_column("Operation", style="cyan")
        table.add_column("Count", justify="right")
        table.add_column("Avg (s)", justify="right")
        table.add_column("Min (s)", justify="right")
        table.add_column("Max (s)", justify="right")
        table.add_column("Total (s)", justify="right")

        for op, stats in sorted(report.items(), key=lambda x: x[1]["total"], reverse=True):
            table.add_row(
                op,
                str(stats["count"]),
                f"{stats['avg']:.3f}",
                f"{stats['min']:.3f}",
                f"{stats['max']:.3f}",
                f"{stats['total']:.3f}",
            )

        console.print(table)


# 全局性能监控器
_perf_monitor = PerformanceMonitor()


def get_perf_monitor() -> PerformanceMonitor:
    """获取性能监控器"""
    return _perf_monitor
