"""笔记 CRUD 操作"""

import logging
import os
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml

from .config import ZKConfig, config
from .models import Note, NoteType

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# 笔记生命周期事件注册表
#
# 核心存储层只"广播"生命周期事件（delete/archive/promote/reject），不主动调用
# 任何特性层。特性层（如 dedup 表同步）通过 register_lifecycle_hook
# 订阅，依赖方向保持 特性 → 存储 单向（分层约束见 CLAUDE.md『Core Data Flow』）。
# ---------------------------------------------------------------------------
_LIFECYCLE_HOOKS: Dict[str, List[Any]] = {}


def register_lifecycle_hook(event: str, callback: Any) -> None:
    """注册笔记生命周期回调（幂等：同一 callback 重复注册不叠加）。

    Args:
        event: 事件名，约定 post_delete / post_archive / post_promote / post_reject
        callback: 回调，签名 callback(note_id=<str>, note_type=<NoteType>, **payload)
    """
    cbs = _LIFECYCLE_HOOKS.setdefault(event, [])
    if callback not in cbs:
        cbs.append(callback)


def unregister_lifecycle_hook(event: str, callback: Any) -> None:
    """取消注册（主要用于测试清理）。"""
    cbs = _LIFECYCLE_HOOKS.get(event, [])
    if callback in cbs:
        cbs.remove(callback)


def _dispatch(event: str, **payload: Any) -> None:
    """触发某事件的全部回调。单个回调抛异常仅 warning（含 note_id + 回调名，
    便于定位具体笔记），不影响其他回调，也不向调用方抛（与原 'dedup 同步
    失败不阻塞主流程' 语义一致）。"""
    note_id = payload.get("note_id")
    for cb in list(_LIFECYCLE_HOOKS.get(event, [])):
        try:
            cb(**payload)
        except Exception as e:  # noqa: BLE001 — 订阅器故障不得阻塞存储主流程
            logger.warning(
                "lifecycle hook %s 失败 cb=%s note=%s: %s",
                event,
                getattr(cb, "__name__", cb),
                note_id,
                e,
            )


def generate_id() -> str:
    """
    生成唯一 ID

    格式: 时间戳 + 4位随机数 (共18位)
    例如: 202603242325281234
    """
    import random

    timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
    random_suffix = random.randint(0, 9999)
    return f"{timestamp}{random_suffix:04d}"


def create_note(
    content: str,
    title: Optional[str] = None,
    note_type: NoteType = NoteType.FLEETING,
    tags: Optional[List[str]] = None,
    links: Optional[List[str]] = None,
    source: Optional[str] = None,
    topic: Optional[str] = None,
) -> Note:
    """创建新笔记"""
    note_id = generate_id()
    now = datetime.now()

    # 如果没有标题，从内容提取
    if title is None:
        title = content[:50] + "..." if len(content) > 50 else content

    note = Note(
        id=note_id,
        title=title,
        content=content,
        type=note_type,
        created=now,
        updated=now,
        tags=tags or [],
        links=links or [],
        backlinks=[],
        source=source,
        topic=topic,
    )

    return note


def _atomic_write(filepath: Path, content: str) -> None:
    """原子写入：先写临时文件再原子替换，防止崩溃产生空文件"""
    filepath.parent.mkdir(parents=True, exist_ok=True)
    tmp_fd = -1
    tmp_path = ""
    try:
        tmp_fd, tmp_path = tempfile.mkstemp(dir=filepath.parent, suffix=".tmp")
        with os.fdopen(tmp_fd, "w", encoding="utf-8") as f:
            tmp_fd = -1  # fd 已移交 fdopen 管理
            f.write(content)
        # 保留目标文件权限（如已存在）
        if filepath.exists():
            try:
                os.chmod(tmp_path, filepath.stat().st_mode)
            except OSError:
                pass
        os.replace(tmp_path, filepath)
    except BaseException:
        if tmp_fd >= 0:
            try:
                os.close(tmp_fd)
            except OSError:
                pass
        if tmp_path:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
        raise


def save_note(note: Note, add_to_index: bool = True) -> bool:
    """保存笔记到文件"""
    try:
        _atomic_write(note.filepath, note.to_markdown())

        logger.info(f"Saved note to {note.filepath}")

        # 添加到向量索引
        if add_to_index:
            from .vector_store import get_vector_store

            vector_store = get_vector_store()
            vector_store.add_note(note)

            # 添加到 BM25 索引
            try:
                from .bm25_index import get_bm25_index

                bm25_index = get_bm25_index()
                content = f"{note.title} {note.content}"
                bm25_index.add_document(
                    note.id, content, note_type=note.type.value if note.type else None
                )
            except Exception as e:
                logger.warning(f"Failed to add note to BM25 index: {e}")

        return True

    except Exception as e:
        logger.error(f"Failed to save note: {e}")
        return False


def load_note(filepath: Path) -> Optional[Note]:
    """从文件加载笔记"""
    try:
        with open(filepath, "r", encoding="utf-8") as f:
            content = f.read()

        return Note.from_markdown(content, filepath)

    except UnicodeDecodeError as e:
        logger.error(f"Failed to load note from {filepath}: {e}")
        return None
    except (ValueError, yaml.YAMLError) as e:
        logger.warning(f"Failed to load note from {filepath}: {e}")
        return None
    except Exception as e:
        logger.error(f"Failed to load note from {filepath}: {e}")
        return None


def load_note_by_id(note_id: str, cfg: Optional[ZKConfig] = None) -> Optional[Note]:
    """
    通过 ID 加载笔记

    Args:
        note_id: 笔记 ID
        cfg: 可选的配置对象，默认使用全局 config

    Returns:
        Note 对象或 None
    """
    use_config = cfg or config

    # 在所有类型目录中搜索
    for note_type in NoteType:
        dir_path = use_config.notes_dir / note_type.value
        if not dir_path.exists():
            continue

        # 尝试两种文件名模式：
        # 1. {id}*.md — literature/permanent 笔记（{id}-{slug}.md）
        # 2. {id[:8]}-{id[8:]}*.md — fleeting 笔记（YYYYMMDD-HHMMSSNNNN.md）
        for filepath in dir_path.glob(f"{note_id}*.md"):
            return load_note(filepath)
        # fleeting 笔记文件名格式：YYYYMMDD-HHMMSSNNNN.md
        if len(note_id) > 8:
            for filepath in dir_path.glob(f"{note_id[:8]}-{note_id[8:]}*.md"):
                return load_note(filepath)

    return None


def list_notes(
    note_type: Optional[NoteType] = None,
    limit: Optional[int] = None,
    cfg: Optional[ZKConfig] = None,
    tags: Optional[List[str]] = None,
    archived_only: bool = False,
    include_archived: bool = False,
) -> List[Note]:
    """
    列出笔记

    内部通过 NoteIndex 减少不必要的 load_note 调用。

    Args:
        note_type: 笔记类型筛选
        limit: 数量限制
        cfg: 可选的配置对象，默认使用全局 config
        tags: 标签筛选列表（AND 逻辑）
        archived_only: 仅返回已归档笔记
        include_archived: 返回时包含已归档笔记

    Returns:
        笔记列表
    """
    from .note_index import get_note_index

    use_config = cfg or config

    # 通过索引获取匹配的元数据列表（tags/limit 在索引层生效）
    idx = get_note_index(use_config)
    metas = idx.list_meta(
        note_type=note_type,
        tags=tags,
        limit=limit,
        archived_only=archived_only,
        include_archived=include_archived,
    )

    # 只加载匹配到的笔记文件
    notes = []
    skipped = 0
    for meta in metas:
        filepath = Path(meta.filepath)
        note = load_note(filepath)
        if note:
            notes.append(note)
        else:
            skipped += 1

    # skipped: 索引中有效但 load_note 失败的文件
    # index_invalid: 索引层已跳过的无效文件（仅当本查询范围涉及它们时计入）
    index_invalid = 0
    if not note_type:
        # 未限定类型时，所有无效文件都可能被查询到
        index_invalid = len(idx.get_invalid_files())
    else:
        # 限定类型时，只计该类型目录下的无效文件
        type_dir = str(use_config.notes_dir / note_type.value)
        index_invalid = sum(
            1
            for f in idx.get_invalid_files()
            if f.replace("\\", "/").startswith(type_dir.replace("\\", "/"))
        )

    total_skipped = skipped + index_invalid
    if total_skipped > 0:
        logger.warning(f"{total_skipped} 个文件无法加载，已跳过。运行 jfox check 清理。")

    return notes


def delete_note(note_id: str) -> bool:
    """删除笔记"""
    note = load_note_by_id(note_id)
    if not note:
        logger.warning(f"Note {note_id} not found")
        return False

    try:
        # backlinks 增量移除（#386）：把本笔记从各 target 的 backlinks 移除，与
        # promote_note 的增量回填对称。放在删文件之前：中途崩溃后重跑 delete 幂等
        # 收敛（backlinks 已清的 target 被 membership 守卫跳过，只剩删文件）。
        # 单 target 写盘失败仅 warning 不中断；残留悬空由
        # `jfox index rebuild --backlinks` 全量重算兜底。
        # target 损坏/解析失败（如手工编辑 backlinks: null）同样仅 warning 跳过，
        # 保证 delete 主流程不因无关 target 的坏状态而失败。
        from .note_index import get_note_index

        now = datetime.now()
        # 类型守卫（#386 CR）：note.links 可能是手编脏数据（links: null → None，或裸标量
        # → int/str）。非 list 时按空列表处理并 warning，防止 `for tid in <int>` 抛
        # TypeError 落到外层 except → return False → 笔记无法删除。
        if not isinstance(note.links, list):
            logger.warning(
                f"Skip backlink cleanup for note {note_id}: links 类型异常 "
                f"({type(note.links).__name__})，按空列表处理"
            )
        for tid in note.links if isinstance(note.links, list) else []:
            try:
                # 类型守卫（#386 CR）：links 内元素为手编脏数据（如 links: [123]，list 内
                # 嵌 int）时，非 str 的 tid 无法定位笔记，warning 跳过保持可诊断性。
                if not isinstance(tid, str):
                    logger.warning(
                        f"Skip backlink cleanup for target {tid}: links 元素类型异常 "
                        f"({type(tid).__name__})"
                    )
                    continue
                t = load_note_by_id(tid)
                if not t:
                    continue
                # 类型守卫（#386 CR）：t.backlinks 为坏类型（None / str / int 标量）时
                # warning 跳过，不写坏 target 数据，保持与 except 分支一致的可诊断性。
                if not isinstance(t.backlinks, list):
                    logger.warning(
                        f"Skip cleaning backlinks from target {tid}: backlinks 类型异常 "
                        f"({type(t.backlinks).__name__})"
                    )
                    continue
                # 类型守卫（#386 CR）：backlinks 元素为手编脏数据（如 backlinks: [123]，
                # list 内嵌 int）时仅 warning 不阻塞——str 引用照常清理，非 str 元素
                # 原样透传（`bid != note_id` 对 int 恒 True，不写入新坏数据）；纯脏 list
                # 下 membership 为 False，不写盘、不触碰坏数据。
                bad_types = sorted(
                    {type(bid).__name__ for bid in t.backlinks if not isinstance(bid, str)}
                )
                if bad_types:
                    logger.warning(
                        f"Cleaning backlinks from target {tid}: backlinks 元素类型异常 "
                        f"({', '.join(bad_types)})，仅清理 str 引用"
                    )
                if note_id in t.backlinks:
                    t.updated = now
                    t.backlinks = [bid for bid in t.backlinks if bid != note_id]
                    # 已知限制：t.filepath 是按 type/标题 slug 重算的路径，非 load 命中的
                    # 磁盘路径；文件名发散时可能另写同 id 双文件（与 promote 回填同病），
                    # 残留由 `jfox index rebuild --backlinks` / `jfox check` 兜底。
                    # 已知限制：本循环无锁 read-modify-write，与常驻 daemon 并发写同一
                    # target 时 last-writer-wins（与 promote 回填 / update_note 同构，全库
                    # 无文件锁，暂不在本 PR 收敛）。
                    _atomic_write(t.filepath, t.to_markdown())
                    get_note_index().update_note_meta(t)
            except Exception as e:
                logger.warning(f"Failed to clean backlinks from target {tid}: {e}")

        # 删除文件
        note.filepath.unlink()
        logger.info(f"Deleted note file: {note.filepath}")

        # 从向量索引删除
        from .vector_store import get_vector_store

        vector_store = get_vector_store()
        vector_store.delete_note(note_id)

        # 从 BM25 索引删除
        try:
            from .bm25_index import get_bm25_index

            bm25_index = get_bm25_index()
            bm25_index.remove_document(note_id)
        except Exception as e:
            logger.warning(f"Failed to remove note from BM25 index: {e}")

        # 广播 post_delete：gem_synth 订阅做 dedup 清理（类型守卫在订阅器）。
        _dispatch("post_delete", note_id=note_id, note_type=note.type)

        return True

    except Exception as e:
        logger.error(f"Failed to delete note {note_id}: {e}")
        return False


def archive_note(note_id: str) -> bool:
    """
    归档笔记（软删除）

    Args:
        note_id: 笔记 ID

    Returns:
        是否成功归档
    """
    n = load_note_by_id(note_id)
    if not n:
        logger.warning(f"Note {note_id} not found")
        return False

    if n.archived:
        logger.info(f"Note {note_id} is already archived")
        # 幂等路径仍刷新 updated 时间戳以符合设计语义
        return update_note(n)

    n.archived = True
    # 先持久化，成功后再广播 post_archive（防 update_note 失败 → 保护已删 → 下轮重复合成）。
    # 类型守卫在 gem_synth 订阅器。
    ok = update_note(n)
    if ok:
        _dispatch("post_archive", note_id=note_id, note_type=n.type)
    return ok


def unarchive_note(note_id: str) -> bool:
    """
    恢复归档笔记

    Args:
        note_id: 笔记 ID

    Returns:
        是否成功恢复
    """
    n = load_note_by_id(note_id)
    if not n:
        logger.warning(f"Note {note_id} not found")
        return False

    if not n.archived:
        logger.info(f"Note {note_id} is not archived")
        # 幂等路径仍刷新 updated 时间戳以符合设计语义
        return update_note(n)

    n.archived = False
    n.reject_reason = None  # 恢复时清空 reject 语义
    if n.type == NoteType.CANDIDATE:
        # candidate reject→unarchive 应回 pending，否则 status='rejected' 残留成僵尸态
        # （默认 candidates list 看不到、--status rejected 还看得到）—— round-2 issue-12
        n.status = "pending"
    return update_note(n)


def promote_note(note_id: str) -> bool:
    """candidate → permanent：改 type、清 candidate 生命周期字段（保留溯源）、移文件、回填 links/backlinks。

    清 status/gem_level/confidence/knowledge_type/reject_reason；**保留 source_fragments/grounded_by**
    做溯源（满足 #249「可追溯到来源碎片」），由 to_markdown 在非空时跨类型写入 frontmatter。
    backlinks 增量回填：解析正文 [[...]]（先剥 code block/HTML 注释防误匹配）→ 精确标题匹配
    → 设本笔记 links + 把本笔记加进各 target 的 backlinks。
    """
    from .note_index import (
        _strip_wiki_link_exclusions,
        extract_wiki_links_from_text,
        get_note_index,
    )

    n = load_note_by_id(note_id)
    if not n:
        logger.warning(f"Note {note_id} not found")
        return False
    if n.type != NoteType.CANDIDATE:
        logger.warning(f"Note {note_id} is not a candidate (type={n.type.value})")
        return False

    # forward links 来源（spec §2.1）：正文 [[标题]] + frontmatter grounded_by 参考笔记，合并去重。
    # 先剥 fenced code block/HTML 注释避免字面量 [[标题]] 误匹配；精确标题匹配，不子串 fallback。
    idx = get_note_index()
    target_ids: List[str] = []
    link_titles = extract_wiki_links_from_text(_strip_wiki_link_exclusions(n.content)) + list(
        n.grounded_by or []
    )
    for title in link_titles:
        if (
            not isinstance(title, str) or not title
        ):  # 过滤非 str/空串（YAML null/int/bool、LLM 脏数据）防 .lower() 崩
            continue
        tm = idx.find_by_title(title)
        if tm is None:
            # spec §6：链接目标不存在 → 警告不阻塞（round-4 issue-5）
            logger.warning(f"promote {note_id}: 链接目标 [[{title}]] 不存在，跳过")
            continue
        if tm.id != n.id and tm.id not in target_ids:
            target_ids.append(tm.id)

    # 改 type + 清 candidate 生命周期字段；**保留 source_fragments/grounded_by 做溯源**
    # （to_markdown 在非空时跨类型写入，promoted permanent 仍可追溯到来源碎片）。
    n.type = NoteType.PERMANENT
    n.status = None
    n.gem_level = None
    n.confidence = None
    n.knowledge_type = None
    n.reject_reason = None
    n.archived = False  # promote 是激活，取消软删除（防 reject→直接 promote 产出 archived permanent）—— round-2 issue-13
    n.links = sorted(set(n.links + target_ids))

    # update_note：filepath 随 type 变 → 写 permanent/ + 删 candidate/ 旧文件 + 更新索引
    if not update_note(n):
        return False

    # 增量回填：把本笔记加进每个 target 的 backlinks（刷 updated 时间戳，因为 backlinks 已变更）。
    # 单 target 写盘/索引失败只 warning 不中断——主笔记已 promote 成功；若发生不对称（本笔记 links
    # 已落盘但某 target backlinks 缺失），用 `jfox index rebuild --backlinks` 全量重算修复。
    now = datetime.now()
    for tid in target_ids:
        t = load_note_by_id(tid)
        if t and n.id not in t.backlinks:
            t.updated = now
            t.backlinks = sorted(set(t.backlinks + [n.id]))
            try:
                _atomic_write(t.filepath, t.to_markdown())
                get_note_index().update_note_meta(t)
            except Exception as e:
                logger.warning(f"Failed to backfill backlinks for target {tid}: {e}")
    # 广播 post_promote：gem_synth 订阅把 dedup 表 note_type 改 permanent。
    _dispatch("post_promote", note_id=note_id, note_type=n.type)
    return True


def reject_note(note_id: str, reason: Optional[str] = None) -> bool:
    """candidate 归档丢弃（软删除）：置 archived=True + status=rejected，可选记 reject_reason。
    直接改字段 + 单次 update_note（不调 archive_note，避免二次写盘）。可 jfox unarchive 恢复。"""
    n = load_note_by_id(note_id)
    if not n:
        logger.warning(f"Note {note_id} not found")
        return False
    if n.type != NoteType.CANDIDATE:
        logger.warning(f"Note {note_id} is not a candidate (type={n.type.value})")
        return False
    n.archived = True
    n.status = "rejected"
    if reason:
        n.reject_reason = reason
    # 先持久化，成功后再广播 post_reject（防 update_note 失败 → 保护已删 → 下轮重复合成）。
    # gem_synth 订阅做 dedup 清理 + 释放被阻断锚点（类型守卫在订阅器）。
    ok = update_note(n)
    if ok:
        _dispatch("post_reject", note_id=note_id, note_type=n.type)
    return ok


def update_note(note_obj: Note, add_to_index: bool = True) -> bool:
    """
    更新已有笔记

    处理：查找旧文件 → 更新 updated 时间戳 → 写入新文件 → 删除旧文件（如路径变化）→ 更新索引

    Args:
        note_obj: 已修改的 Note 对象（必须已有 id）
        add_to_index: 是否更新搜索索引

    Returns:
        是否更新成功
    """
    # 查找当前文件路径（可能标题改了，按 ID 查）
    old_filepath = find_note_file(config, note_obj.id)
    if not old_filepath:
        logger.warning(f"Note {note_obj.id} file not found on disk")
        return False

    try:
        # 更新时间戳
        note_obj.updated = datetime.now()

        # 写入新文件（filepath 属性根据当前字段生成）
        _atomic_write(note_obj.filepath, note_obj.to_markdown())

        # 如果文件路径变了（标题修改导致重命名），删除旧文件
        if old_filepath != note_obj.filepath and old_filepath.exists():
            old_filepath.unlink()
            logger.info(f"Renamed note file: {old_filepath} -> {note_obj.filepath}")

        logger.info(f"Updated note {note_obj.id}")

        # 更新索引
        if add_to_index:
            # 先删除旧索引，再添加新索引
            try:
                from .vector_store import get_vector_store

                vector_store = get_vector_store()
                vector_store.delete_note(note_obj.id)
                vector_store.add_note(note_obj)
            except Exception as e:
                logger.warning(f"Failed to update vector store index: {e}")

            try:
                from .bm25_index import get_bm25_index

                bm25_index = get_bm25_index()
                bm25_index.remove_document(note_obj.id)
                content = f"{note_obj.title} {note_obj.content}"
                bm25_index.add_document(
                    note_obj.id,
                    content,
                    note_type=note_obj.type.value if note_obj.type else None,
                )
            except Exception as e:
                logger.warning(f"Failed to update BM25 index: {e}")

        # 同步刷新 NoteIndex 缓存，避免同进程内读取到旧的归档状态
        try:
            from .note_index import get_note_index

            idx = get_note_index()
            idx.update_note_meta(note_obj)
        except Exception as e:
            logger.warning(f"Failed to update note index cache: {e}")

        return True

    except Exception as e:
        logger.error(f"Failed to update note {note_obj.id}: {e}")
        return False


def get_stats(cfg: Optional[ZKConfig] = None) -> Dict[str, Any]:
    """
    获取知识库统计

    Args:
        cfg: 可选的配置对象，默认使用全局 config

    Returns:
        统计信息字典
    """
    use_config = cfg or config

    stats = {
        "total": 0,
        "by_type": {},
        "vector_store": {},
    }

    # 统计各类型笔记数量
    for note_type in NoteType:
        dir_path = use_config.notes_dir / note_type.value
        if dir_path.exists():
            count = len(list(dir_path.glob("*.md")))
            stats["by_type"][note_type.value] = count
            stats["total"] += count

    # 向量存储统计
    try:
        from .vector_store import get_vector_store

        vector_store = get_vector_store()
        stats["vector_store"] = vector_store.get_stats()
    except Exception as e:
        logger.warning(f"Failed to get vector store stats: {e}")
        stats["vector_store"] = {"error": str(e)}

    return stats


def search_notes(
    query: str,
    top_k: int = 5,
    note_type: Optional[str] = None,
    mode: str = "hybrid",
    tags: Optional[List[str]] = None,
    include_archived: bool = False,
) -> List[Dict[str, Any]]:
    """
    搜索笔记

    Args:
        query: 搜索查询
        top_k: 返回结果数量
        note_type: 笔记类型筛选
        mode: 搜索模式 - "hybrid"(混合), "semantic"(语义), "keyword"(关键词)
        tags: 标签筛选列表（AND 逻辑）
        include_archived: 是否包含已归档笔记，默认排除

    Returns:
        搜索结果列表
    """
    from .search_engine import SearchMode, get_search_engine

    search_engine = get_search_engine()

    # 转换模式
    mode_map = {
        "hybrid": SearchMode.HYBRID,
        "semantic": SearchMode.SEMANTIC,
        "keyword": SearchMode.KEYWORD,
    }
    search_mode = mode_map.get(mode.lower(), SearchMode.HYBRID)

    return search_engine.search(
        query,
        top_k=top_k,
        mode=search_mode,
        note_type=note_type,
        tags=tags,
        include_archived=include_archived,
    )


def extract_keywords(content: str, max_keywords: int = 10) -> List[str]:
    """
    从内容中提取关键词

    简单实现：提取长度在 2-20 之间的单词/词组，排除常见停用词

    Args:
        content: 文本内容
        max_keywords: 最大关键词数量

    Returns:
        关键词列表
    """
    import re

    # 常见中文和英文停用词
    stopwords = {
        "the",
        "a",
        "an",
        "is",
        "are",
        "was",
        "were",
        "be",
        "been",
        "being",
        "have",
        "has",
        "had",
        "do",
        "does",
        "did",
        "will",
        "would",
        "could",
        "should",
        "may",
        "might",
        "must",
        "shall",
        "can",
        "need",
        "dare",
        "ought",
        "used",
        "to",
        "of",
        "in",
        "for",
        "on",
        "with",
        "at",
        "by",
        "from",
        "as",
        "into",
        "through",
        "during",
        "before",
        "after",
        "above",
        "below",
        "between",
        "under",
        "and",
        "but",
        "or",
        "yet",
        "so",
        "if",
        "because",
        "although",
        "though",
        "while",
        "where",
        "when",
        "that",
        "which",
        "who",
        "whom",
        "whose",
        "what",
        "this",
        "these",
        "those",
        "i",
        "you",
        "he",
        "she",
        "it",
        "we",
        "they",
        "me",
        "him",
        "her",
        "us",
        "them",
        "my",
        "your",
        "his",
        "its",
        "our",
        "their",
        "这里",
        "那里",
        "这个",
        "那个",
        "什么",
        "怎么",
        "为什么",
        "因为",
        "所以",
        "但是",
        "如果",
        "虽然",
        "而且",
        "或者",
        "和",
        "与",
        "的",
        "了",
        "在",
        "是",
        "我",
        "你",
        "他",
        "她",
        "它",
        "们",
        "有",
        "没有",
        "一个",
        "一种",
        "一些",
        "可以",
        "需要",
        "应该",
        "能够",
        "已经",
        "现在",
        "今天",
        "明天",
        "昨天",
        "这样",
        "那样",
        "如何",
        "谁",
        "哪",
        "哪些",
        "哪里",
        "什么时候",
        "怎样",
        "非常",
        "很",
        "太",
        "最",
        "更",
        "比较",
        "相当",
        "真的",
        "确实",
        "当然",
        "可能",
        "也许",
        "大概",
        "一定",
        "必须",
        "得",
        "地",
        "着",
        "过",
        "把",
        "被",
        "让",
        "给",
        "向",
        "从",
        "到",
        "对于",
        "关于",
        "由于",
        "根据",
        "按照",
        "通过",
        "随着",
        "除了",
        "包括",
        "涉及",
        "有关",
        "学习",
        "使用",
        "实现",
        "添加",
        "创建",
        "记录",
        "今天",
        "一下",
    }

    # 提取潜在关键词（2-20 个字符的词组）
    # 匹配中文字符串或英文单词
    pattern = r"[\u4e00-\u9fff]{2,10}|[a-zA-Z][a-zA-Z0-9_]{1,15}"
    matches = re.findall(pattern, content.lower())

    # 统计词频
    word_counts = {}
    for word in matches:
        if word not in stopwords and len(word) >= 2:
            word_counts[word] = word_counts.get(word, 0) + 1

    # 按词频排序，返回前 max_keywords 个
    sorted_words = sorted(word_counts.items(), key=lambda x: x[1], reverse=True)
    return [word for word, count in sorted_words[:max_keywords]]


def suggest_links(
    content: str,
    top_k: int = 5,
    threshold: float = 0.6,
    exclude_ids: Optional[List[str]] = None,
    cfg: Optional[ZKConfig] = None,
) -> List[Dict[str, Any]]:
    """
    根据内容推荐可以链接的已有笔记

    使用语义相似度 + 关键词匹配的混合策略

    Args:
        content: 输入内容
        top_k: 返回建议数量
        threshold: 相似度阈值（0-1）
        exclude_ids: 要排除的笔记 ID 列表
        cfg: 可选的配置对象，默认使用全局 config

    Returns:
        建议链接的笔记列表，按置信度排序
    """
    exclude_ids = exclude_ids or []
    suggestions = []
    seen_ids = set(exclude_ids)

    # 1. 语义搜索 - 获取相似笔记
    try:
        semantic_results = search_notes(content, top_k=top_k * 2)
        for r in semantic_results:
            note_id = r.get("id")
            if note_id and note_id not in seen_ids:
                score = r.get("score", 0)
                if score >= threshold:
                    suggestions.append(
                        {
                            "id": note_id,
                            "title": r.get("metadata", {}).get("title", "Untitled"),
                            "type": r.get("metadata", {}).get("type", "unknown"),
                            "score": round(score, 3),
                            "match_type": "semantic",
                            "preview": (
                                r.get("document", "")[:150] + "..." if r.get("document") else ""
                            ),
                        }
                    )
                    seen_ids.add(note_id)
    except Exception as e:
        logger.warning(f"Semantic search failed in suggest_links: {e}")

    # 2. 关键词匹配 - 作为补充
    try:
        keywords = extract_keywords(content, max_keywords=5)
        if keywords:
            all_notes = list_notes(limit=200, cfg=cfg)  # 获取足够多的笔记用于匹配

            for note in all_notes:
                if note.id in seen_ids:
                    continue

                # 计算关键词匹配分数
                note_text = f"{note.title} {' '.join(note.tags)} {note.content[:500]}"
                note_text_lower = note_text.lower()

                match_count = 0
                for kw in keywords:
                    if kw.lower() in note_text_lower:
                        match_count += 1

                if match_count > 0:
                    # 关键词匹配分数 (0.3 - 0.6)
                    keyword_score = 0.3 + (match_count / len(keywords)) * 0.3

                    # 如果分数达到阈值且结果数量不足，添加
                    if keyword_score >= threshold * 0.5 and len(suggestions) < top_k * 2:
                        suggestions.append(
                            {
                                "id": note.id,
                                "title": note.title,
                                "type": note.type.value,
                                "score": round(keyword_score, 3),
                                "match_type": "keyword",
                                "matched_keywords": [
                                    kw for kw in keywords if kw.lower() in note_text_lower
                                ],
                                "preview": note.content[:150] + "..." if note.content else "",
                            }
                        )
                        seen_ids.add(note.id)
    except Exception as e:
        logger.warning(f"Keyword matching failed in suggest_links: {e}")

    # 3. 按分数排序并返回前 top_k 个
    suggestions.sort(key=lambda x: x["score"], reverse=True)
    return suggestions[:top_k]


def find_note_file(config_obj, note_id: str) -> Optional[Path]:
    """
    通过 ID 查找笔记文件路径

    Args:
        config_obj: ZKConfig 配置对象
        note_id: 笔记 ID

    Returns:
        文件路径或 None
    """
    for note_type in NoteType:
        dir_path = config_obj.notes_dir / note_type.value
        if not dir_path.exists():
            continue

        # 尝试两种文件名模式：
        # 1. {id}*.md — literature/permanent 笔记（{id}-{slug}.md）
        # 2. {id[:8]}-{id[8:]}*.md — fleeting 笔记（YYYYMMDD-HHMMSSNNNN.md）
        for filepath in dir_path.glob(f"{note_id}*.md"):
            return filepath
        if len(note_id) > 8:
            for filepath in dir_path.glob(f"{note_id[:8]}-{note_id[8:]}*.md"):
                return filepath

    return None


class NoteManager:
    """笔记管理器类，用于面向对象的操作"""

    @staticmethod
    def load_note(filepath: Path) -> Optional[Note]:
        """从文件加载笔记"""
        return load_note_static(filepath)

    @staticmethod
    def find_note_file(config_obj, note_id: str) -> Optional[Path]:
        """通过 ID 查找笔记文件路径"""
        return find_note_file(config_obj, note_id)


def load_note_static(filepath: Path) -> Optional[Note]:
    """从文件加载笔记（静态版本）"""
    try:
        with open(filepath, "r", encoding="utf-8") as f:
            content = f.read()

        return Note.from_markdown(content, filepath)

    except UnicodeDecodeError as e:
        logger.error(f"Failed to load note from {filepath}: {e}")
        return None
    except (ValueError, yaml.YAMLError) as e:
        logger.warning(f"Failed to load note from {filepath}: {e}")
        return None
    except Exception as e:
        logger.error(f"Failed to load note from {filepath}: {e}")
        return None
