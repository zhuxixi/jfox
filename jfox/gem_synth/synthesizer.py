"""合成编排：单个锚点 → transcript 上下文 → grounding → LLM → candidate 笔记 + 记账。

单个锚点的完整 L3 合成流水线。daemon 循环（Phase F）会对每个未处理锚点调用
synthesize_anchor；本模块只负责"一个锚点 -> 一条 candidate"的单步编排，
不涉及循环、限速、调度。
"""

import logging
import re
import threading
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional

from ..global_config import GemSynthesisConfig
from ..models import GemLevel, Note, NoteType
from ..note import load_note_by_id, save_note, update_note
from .dedup import (
    DedupHit,
    _append_knowledge_section,
    _clean_candidate_content,
    _resolve_kb_name,
    dedup_check,
    upsert_dedup,
)
from .grounding import fetch_grounding
from .llm import extract_delta_with_llm, synthesize_with_llm
from .transcript import extract_turn_around

logger = logging.getLogger(__name__)


def _safe_float(value, default: float = 0.0) -> float:
    """安全转 float：LLM 可能返回 "high" 等非数值字符串，直接 float() 会抛 ValueError。"""
    try:
        return float(value) if value is not None else default
    except (TypeError, ValueError):
        return default


def _coerce_grounded_by(value) -> list:
    """grounded_by 类型安全：LLM 偶发返回字符串（如 "笔记A"），list() 会拆成字符。
    统一成 list；非 list/非空 字符串包成单元素列表。"""
    if isinstance(value, list):
        return value
    if value:
        return [value]
    return []


# content 开头冗余 H1 的正则：串首 \A + 前导空白 \s* + `# 文本` + 尾随换行 \n*。
# 比 Note.from_markdown（models.py:179 `^# .+\n+`）故意放宽（合成侧兜底 LLM 退化输出：
# 前导空白行、无尾换行 H1），非严格对称——详见 _strip_leading_h1 docstring（cc R3-issue5）。
_LEADING_H1_RE = re.compile(r"\A\s*# .+\n*")

# 近逐字阈值：cosine ≥ 此值视为近乎逐字重复，跳过 delta LLM 省成本（backlog 大量逐字 dup）。
# 0.88–0.96 才进入「提取增量」合并带（左闭右开：≥ dedup_threshold 且 < 0.96）。v1 不暴露配置。
# 注：若用户把 dedup_threshold 调到 ≥0.96（只把近逐字当重复），合并带为空、所有命中走
# 近逐字跳过——预期语义（近逐字无实质增量），非 bug（cc round-1 issue-4 acknowledged）。
_NEAR_VERBATIM_THRESHOLD = 0.96


def _strip_leading_h1(content: str) -> str:
    r"""剥掉 content 开头首个冗余 H1 行，消除 candidate 双 H1（#320）。

    title 已单独存 frontmatter、to_markdown 会前置 `# title`，故 LLM content 若以
    `# 标题` 开头即为冗余（双 H1 根因）。仅剥**首个** leading H1；正文内的 H1 分节
    （3+H1 场景，LLM 误用 H1 当分节）超出 #320 范围、留给 #319。

    正则 `\A\s*# .+\n*` 比 Note.from_markdown（models.py:179 `^# .+\n+`）**故意放宽**
    （cc R3-issue5）：`\s*` 吃掉 H1 前导空白行、`\n*` 覆盖无尾随换行的退化输出（如
    content 恰为 `# 标题`）。合成侧需兜底 LLM 退化输出，故比解析侧（from_markdown
    只处理规范落盘文件）更宽松，两者非严格对称。content 仅含单个 H1 时返回空串
    （_save_candidate_note 会追加来源/置信度章节不会产出空笔记；kimi R1 移除原回退
    以彻底消除该边界双 H1）。
    """
    return _LEADING_H1_RE.sub("", content, count=1)


def _try_merge_delta(
    hit: DedupHit,
    new_content: str,
    anchor: Dict[str, Any],
    cfg: GemSynthesisConfig,
    kb: str,
    stop_event: Optional[threading.Event],
) -> bool:
    """命中 candidate 合并带时：load 已有 → 提取增量 → 合并。任一步失败/无增量返回 False
    （调用方据此 mark_duplicate 降级，不阻塞合成）。"""
    try:
        existing = load_note_by_id(hit.note_id)
        if existing is None or existing.type != NoteType.CANDIDATE or existing.archived:
            logger.info("合并目标 %s 不可用（已删/晋升/归档），降级跳过", hit.note_id)
            return False
        # 记下版本（updated）与正文口径，LLM 调用后复比对（防 TOCTOU）
        updated_before = existing.updated
        delta = extract_delta_with_llm(
            new_content=new_content,
            existing_content=_clean_candidate_content(existing.content),
            cfg=cfg,
            stop_event=stop_event,
        )
        # has_delta=True 但 delta 正文空/空白 → 视为无实质增量（防空 ## 补充 段污染草稿）
        if delta is None or not delta.get("has_delta") or not str(delta.get("delta") or "").strip():
            logger.info("锚点 #%s 无实质增量，跳过", anchor.get("fragment_id"))
            return False
        # TOCTOU 复核：extract_delta_with_llm 可长达 claude_timeout_seconds（默认 180s），
        # 期间 candidate 可能被 CLI promote/archive（改 type/路径）或被其他合并/编辑改正文。
        # 重 load + 复校验 type/archived + updated 版本；任一变更则 delta 基于旧快照、失配，
        # 降级跳过（用 updated 而非正文口径比对：catch 超出 _MAX_CONTENT_CHARS 截断的改动）。
        existing = load_note_by_id(hit.note_id)
        if (
            existing is None
            or existing.type != NoteType.CANDIDATE
            or existing.archived
            or existing.updated != updated_before
        ):
            logger.info("合并目标 %s 在增量提取期间状态/版本变更，降级跳过", hit.note_id)
            return False
        return _merge_delta_into_candidate(existing, delta, anchor, kb)
    except Exception as e:
        logger.exception("增量合并流程异常，降级跳过: %s", e)
        return False


def _merge_delta_into_candidate(
    existing_note: Note, delta: Dict[str, Any], anchor: Dict[str, Any], kb: str
) -> bool:
    """把增量补进已有 candidate 草稿（in-place 追加）。失败返回 False（调用方降级跳过）。

    调用方已 load + 校验过 existing_note（非 None / 非 archived / type=CANDIDATE）。
    把 `## 补充` 段插进 body 末尾、元数据段落（## 来源/置信度）**之前** →
    _clean_candidate_content（从 ## 来源 截断）保留该段 → 增量进 embedding 口径 +
    喂给后续 delta LLM 的 existing_content 也能看到（防同一增量被相似锚点反复提取）。
    update_note 落盘后 upsert_dedup 重算 embedding（body 含 delta → content_hash 变）。

    delta: {has_delta: True, delta: str, conflict: Optional[str]}（extract_delta_with_llm 返回）。
    """
    try:
        # 强制 str：LLM 偶发返回非字符串 delta（list/int），避免拼进 Markdown 产生异常内容
        delta_text = str(delta.get("delta") or "")
        # delta 来自 LLM 处理不可信 transcript 的输出，原样进 candidate 正文：candidate 是
        # L5 待审草稿，--allowed-tools "" 已禁工具无 RCE；wiki-link [[ ]] 注入仅产反链、审阅
        # 可见。v1 接受（follow-up 可在插入前 strip [[ ]]）。
        section = (
            f"\n\n## 补充（来自锚点 #{anchor.get('fragment_id', '?')} "
            f"@ {anchor.get('timestamp', '')}）\n{delta_text}\n"
        )
        conflict = str(delta.get("conflict") or "").strip()
        if conflict:
            section += f"\n> ⚠️ 矛盾：{conflict}\n"
        existing_note.content = _append_knowledge_section(existing_note.content, section)
        # update_note 返回 False（find_note_file 落空 / 原子写异常，不抛）→ 候选被并发删改，
        # 不重算 embedding、返回 False 降级
        if not update_note(existing_note, add_to_index=False):
            logger.warning(
                "update_note 返回 False（候选被并发删改？），跳过重算 embedding note=%s",
                existing_note.id,
            )
            return False
        # 重算 embedding 失败（daemon 不可用等）仅 warning：合并已在磁盘生效（返回 True），
        # dedup 口径暂时 stale，下轮 dedup-backfill 自愈
        if not upsert_dedup(kb, existing_note.id, "candidate", existing_note.content):
            logger.warning(
                "合并后重算 embedding 失败（daemon 不可用？），dedup 口径暂 stale，backfill 自愈 note=%s",
                existing_note.id,
            )
        return True
    except Exception as e:
        logger.exception("合并增量进 candidate 失败 note=%s: %s", existing_note.id, e)
        return False


def _save_candidate_note(llm_result: Dict[str, Any], anchor: Dict[str, Any]) -> Optional[str]:
    """把 LLM 结果存成 candidate 笔记，返回 note id。失败返回 None。

    笔记落盘路径：<kb>/notes/candidate/<id>-<slug>.md（由 Note.filepath 根据
    NoteType.CANDIDATE + 全局 config.notes_dir 推导）。KB 上下文由调用方
    （daemon loop 外层 use_kb）提供，本函数不再内部 use_kb。

    整个构造 + 落盘都包在 try 内：anchor 字段缺失（KeyError）或 Note 构造异常
    都转成"跳过该锚点"（返回 None），不抛穿到循环导致整轮失败。
    """
    try:
        now = datetime.now()
        # 时间戳 + 微秒，避免同秒碰撞（candidate 不进 note_index，14 位约定不适用）
        note_id = now.strftime("%Y%m%d%H%M%S") + "-" + now.strftime("%f")
        title = llm_result.get("title") or "未命名候选宝石"
        # 自守 strip：即便被独立调用（不经 synthesize_anchor 入口归一化）也消除开头冗余 H1
        # （cc R2-issue2 防御）。幂等——synthesize_anchor 入口已 strip 时此处无 H1 不变
        content = _strip_leading_h1(llm_result.get("content") or "")

        # 追加来源 / 基准 / 置信度元信息（便于 L5 审阅与溯源）
        # anchor['fragment_id']/['timestamp']/['session_id'] 在 try 内访问：
        # 缺键时 KeyError 被捕获 → 返回 None 跳过该锚点，而非抛穿循环
        source_section = (
            f"\n\n## 来源\n- 碎片 #{anchor['fragment_id']} @ {anchor['timestamp']}\n"
            f"- session `{anchor['session_id']}`\n"
        )
        grounding_section = ""
        grounded_by = _coerce_grounded_by(llm_result.get("grounded_by"))
        if grounded_by:
            links = ", ".join(f"[[{g}]]" for g in grounded_by)
            grounding_section = f"\n## 参考的永久笔记\n{links}\n"
        conf_section = f"\n## 置信度\n{llm_result.get('confidence', '?')}\n"

        # Note() 构造也在 try 内：任何字段异常（如类型/格式）都应转成"跳过"而非抛穿
        note = Note(
            id=note_id,
            title=title,
            content=content + source_section + grounding_section + conf_section,
            type=NoteType.CANDIDATE,
            created=now,
            updated=now,
            gem_level=GemLevel.FLAWED.value,
            confidence=_safe_float(llm_result.get("confidence"), 0.0),
            source_fragments=[anchor["fragment_id"]],
            grounded_by=grounded_by,
            knowledge_type=llm_result.get("knowledge_type"),
            status="pending",
        )
        _persist_note(note)
        return note_id
    except Exception as e:
        logger.exception("保存 candidate 笔记失败: %s", e)
        return None


def _persist_note(note: Note) -> None:
    """实际落盘。封装一层适配 note.py 的 save API。

    不再 use_kb(kb)：调用方（daemon loop 的 _tick_once 外层 use_kb(cfg.target_kb)）
    已切到目标 KB，内部再 use_kb 会每锚点 _reset_singletons（重载 embedding 模型）。
    add_to_index=False：避免在 daemon 进程里意外触发向量/BM25 索引（candidate 是
    待审草稿，索引可由 Phase G/H 或显式 reindex 补上）。
    """
    ok = save_note(note, add_to_index=False)
    if not ok:
        raise RuntimeError(f"save_note 返回 False（note_id={note.id}）")


def synthesize_anchor(
    anchor: Dict[str, Any],
    log,
    cfg: GemSynthesisConfig,
    stop_event: Optional[threading.Event] = None,
) -> Optional[Dict[str, Any]]:
    """合成单个锚点。成功返回 {candidate_note_id, title, confidence}，跳过/失败返回 None。

    流程：
      1. 无 transcript_path → mark_failed 记账（不重试）
      2. extract_turn_around 抽不到上下文 → mark_failed 记账（不重试）
      3. fetch_grounding 检索 permanent 基准
      4. synthesize_with_llm 调 LLM；None → mark_failed 记账（不重试）
      5. _save_candidate_note 落盘 + log.mark_processed 记账

    每条失败路径都调 log.mark_failed，使 daemon 过夜跑不会对坏锚点无限重试。
    stop_event 透传给 synthesize_with_llm → _invoke_claude，使 daemon shutdown /
    任务中断能在 claude 调用进行中触发（而非等满 timeout）。
    """
    transcript_path = anchor.get("transcript_path")
    if not transcript_path:
        logger.info("锚点 #%s 无 transcript_path，mark_failed", anchor["fragment_id"])
        log.mark_failed(anchor["fragment_id"], "no transcript_path")
        return None

    turn = extract_turn_around(Path(transcript_path), anchor.get("content") or "")
    if not turn.strip():
        logger.info("锚点 #%s 提取不到上下文，mark_failed", anchor["fragment_id"])
        log.mark_failed(anchor["fragment_id"], "empty transcript context")
        return None

    grounding = fetch_grounding(anchor.get("content") or "", top_k=cfg.grounding_top_k)

    llm_result = synthesize_with_llm(
        turn_context=turn, grounding=grounding, cfg=cfg, stop_event=stop_event
    )
    if llm_result is None:
        logger.info(
            "锚点 #%s LLM 合成失败/无效，mark_failed（不重试）",
            anchor["fragment_id"],
        )
        log.mark_failed(anchor["fragment_id"], "llm synthesis failed")
        return None

    # 入口统一 strip 开头冗余 H1（cc R1：口径一致，避免短正文近重复漏检）。用局部 content，
    # 不改 llm_result 原对象（cc R2-issue3：避免 LLM 层缓存/复用结果对象时的副作用）。
    content = _strip_leading_h1(llm_result.get("content") or "")
    # LLM 退化输出（content 仅 H1、无正文）strip 后为空 → mark_failed，不落盘无知识
    # candidate（kimi R2：与 'llm synthesis failed' 路径对称，避免退化进 L5 审阅队列）
    if not content.strip():
        logger.info(
            "锚点 #%s content strip 后为空（LLM 退化输出），mark_failed", anchor["fragment_id"]
        )
        log.mark_failed(anchor["fragment_id"], "empty content after h1 strip")
        return None

    # 存盘前去重：命中则不存盘、记 duplicate，锚点算处理完（不重试）
    # target_kb=None 表示用 default；解析成具体 KB 名（dedup_embeddings.kb 是
    # NOT NULL，且 None 会让 dedup_check 的 WHERE kb=? 匹配 0 行→永远检不到重复）
    kb_name = _resolve_kb_name(cfg.target_kb)
    if getattr(cfg, "dedup_enabled", True):
        hit = dedup_check(
            kb_name,
            content,
            threshold=getattr(cfg, "dedup_threshold", 0.88),
        )
        if hit:
            # 增量合并决策（#309）：仅 candidate + 合并带(0.88–0.96) + merge 开 才提取增量；
            # permanent / 近逐字 / merge 关 / 任何失败 → 一律 mark_duplicate 跳过（不阻塞合成）
            merge_eligible = (
                getattr(cfg, "dedup_merge_enabled", True)
                and hit.note_type == NoteType.CANDIDATE.value
                and hit.score < _NEAR_VERBATIM_THRESHOLD
            )
            merged = False
            if merge_eligible:
                merged = _try_merge_delta(hit, content, anchor, cfg, kb_name, stop_event)
            if merged:
                log.mark_merged(anchor["fragment_id"], hit.note_id)
                logger.info(
                    "锚点 #%s 命中重复并增量合并进 %s（score=%.3f）",
                    anchor["fragment_id"],
                    hit.note_id,
                    hit.score,
                )
            else:
                log.mark_duplicate(anchor["fragment_id"], hit.note_id)
                logger.info(
                    "锚点 #%s 命中重复（dup_of=%s, score=%.3f），跳过存盘",
                    anchor["fragment_id"],
                    hit.note_id,
                    hit.score,
                )
            return None

    note_id = _save_candidate_note(llm_result, anchor)
    if note_id is None:
        log.mark_failed(anchor["fragment_id"], "save candidate note failed")
        return None

    # 存盘成功 → 入 dedup 库（供后续锚点查重）；dedup 关闭时跳过
    # （spec §11：dedup_enabled=False 完全关闭回到原行为，不为每条 candidate 算 embedding 灌库）
    if getattr(cfg, "dedup_enabled", True):
        upsert_dedup(kb_name, note_id, "candidate", content)

    log.mark_processed(anchor_fragment_id=anchor["fragment_id"], candidate_note_id=note_id)
    return {
        "candidate_note_id": note_id,
        "title": llm_result.get("title"),
        "confidence": llm_result.get("confidence"),
    }


__all__ = ["synthesize_anchor"]
