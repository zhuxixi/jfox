"""add 落库防重（#383）：permanent 笔记创建前的双通道查重闸门。

通道一（标题）：非 archived 同标题（大小写不敏感、不限类型）→ 拦截。
    wiki-link 按标题解析，同标题笔记会导致链接分裂，所以不限笔记类型。
通道二（embedding）：复用 gem_synth.dedup 的正文余弦查重，仅 embedding
    daemon 可用时生效——daemon 不在时 dedup._embed 会退回本地模型加载
    （秒级延迟），必须用 is_daemon_running 前置闸门挡掉。

设计原则：防重是闸门不是路障——除明确命中外，任何内部异常都放行。
"""

import logging
from typing import Optional

logger = logging.getLogger(__name__)

# 短文本跳过 embedding 查重：区分度差，标题通道已兜底（#383 建议值）
_EMBED_DEDUP_MIN_CHARS = 50


class DuplicateNoteError(Exception):
    """add 防重命中。matched_by: "title" | "embedding"；score 仅 embedding 通道有值。"""

    def __init__(
        self,
        matched_id: str,
        matched_title: str,
        matched_by: str,
        score: Optional[float] = None,
    ):
        self.matched_id = matched_id
        self.matched_title = matched_title
        self.matched_by = matched_by
        self.score = score
        detail = f"cosine={score:.3f}" if score is not None else "title match"
        super().__init__(f"已存在重复笔记[{matched_by}] {matched_id} {matched_title!r} ({detail})")


def _load_note_add_config():
    """读取 add 防重全局配置。独立函数便于测试 monkeypatch（避免写真实配置文件）。"""
    from .global_config import get_global_config_manager

    return get_global_config_manager().get_note_add_config()


def _daemon_available() -> bool:
    """embedding daemon 是否在跑。独立函数便于测试 monkeypatch。"""
    try:
        from .daemon.process import is_daemon_running

        return is_daemon_running()
    except Exception:
        return False


def check_add_duplicate(
    title: Optional[str],
    content: str,
    *,
    cfg=None,
) -> None:
    """permanent 落库前查重；命中 raise DuplicateNoteError，其余情况一律放行。

    cfg: 可选 ZKConfig（测试注入临时知识库）；None 用当前 use_kb 上下文。
    """
    try:
        conf = _load_note_add_config()
        if not conf.dedup_enabled:
            return

        from .note_index import get_note_index

        idx = get_note_index(cfg)

        # 通道一：标题（零成本，先查；O(N) 扫描——_by_title 单值映射在
        # 同标题多条 + archived 混存时不可靠，add 路径已有同量级扫描）
        if title and conf.title_dedup:
            title_lower = title.lower()
            for meta in idx.get_all_meta():
                if meta.archived:
                    continue
                if meta.title.lower() == title_lower:
                    raise DuplicateNoteError(meta.id, meta.title, "title")

        # 通道二：正文 embedding（仅 daemon 可用时，防本地模型加载）
        if conf.embedding_dedup and len(content.strip()) > _EMBED_DEDUP_MIN_CHARS:
            if _daemon_available():
                from .gem_synth.dedup import _resolve_kb_name, dedup_check

                kb_name = cfg.base_dir.name if cfg is not None else _resolve_kb_name(None)
                hit = dedup_check(kb_name, content, threshold=conf.dedup_threshold)
                if hit is not None:
                    matched_meta = idx.find_by_id(hit.note_id)
                    matched_title = matched_meta.title if matched_meta else ""
                    raise DuplicateNoteError(
                        hit.note_id, matched_title, "embedding", score=hit.score
                    )
    except DuplicateNoteError:
        raise
    except Exception as e:  # 闸门不是路障：查重自身故障一律放行
        logger.warning("add 防重检查失败，放行: %s", e)
        return


def record_added_permanent(note_id: str, content: str, *, cfg=None) -> None:
    """落库成功后灌 dedup 表（best-effort），让后续 add 与 gem_synth 都能查到。

    仅 daemon 可用时执行（理由同 check_add_duplicate 通道二）；失败仅 warning。
    """
    try:
        if not _daemon_available():
            return
        from .gem_synth.dedup import _resolve_kb_name, upsert_dedup

        kb_name = cfg.base_dir.name if cfg is not None else _resolve_kb_name(None)
        upsert_dedup(kb_name, note_id, "permanent", content)
    except Exception as e:
        logger.warning("add 后 dedup 灌表失败 note=%s: %s", note_id, e)
