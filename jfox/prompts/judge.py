"""session-batch judge 编排：选择 → claim → 证据 → runner → candidate → 记账。

jfox 不实现通用 agent；只执行固定编排、校验结构化结果、保存 candidate、记账。
人工闭环：judge 成功后只写 succeeded + pending，不替用户执行 disposition。
"""

import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from ..global_config import get_global_config_manager
from .grounding import (
    GroundingResult,
    build_prompt_history,
    fetch_judgment_grounding,
    fetch_unresolved_evidence,
)
from .runner import run_runner
from .store import PromptStore
from .transcript import (
    ContextResult,
    TranscriptDocument,
    read_transcript_safe,
    select_context,
)

logger = logging.getLogger(__name__)


@dataclass
class JudgeReport:
    """一次 judge 的报告。"""

    total: int = 0
    succeeded: int = 0
    failed: int = 0
    items: List[Dict[str, Any]] = field(default_factory=list)
    batches: int = 0
    drain: Optional[Dict[str, Any]] = None


def _utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _select_prompt_ids(
    store: PromptStore,
    kb_name: str,
    session_id: Optional[str],
    retry_failed: bool,
    retry_needs_review: bool,
    limit: Optional[int],
) -> List[int]:
    """选择要判断的 prompt ID。"""
    if retry_needs_review:
        judgments = store.list_judgments(kb_name, judgment_state="succeeded", disposition="pending")
        return [j["prompt_id"] for j in judgments if j.get("classification") == "needs_review"][
            : limit or 10000
        ]

    if retry_failed:
        judgments = store.list_judgments(kb_name, judgment_state="failed")
        return [j["prompt_id"] for j in judgments][: limit or 10000]

    # 默认：无 judgment 行的 prompt
    all_prompts = store.list_prompts(session_id=session_id, limit=limit or 10000)
    judged = {j["prompt_id"] for j in store.list_judgments(kb_name, limit=100000)}
    unjudged = [p["prompt_id"] for p in all_prompts if p["prompt_id"] not in judged]
    return unjudged[:limit] if limit else unjudged


def _create_candidate_from_draft(
    draft: Dict[str, Any],
    prompt_id: int,
) -> Optional[str]:
    """把 runner draft 落成 pending candidate 笔记，返回 note id。

    不执行 dedup、不执行 confidence 过滤、不调用增量 merge。
    candidate 创建前检查已有 candidate（幂等恢复）。
    """
    from ..models import GemLevel, Note, NoteType
    from ..note import save_note

    try:
        now = datetime.now()
        note_id = now.strftime("%Y%m%d%H%M%S") + "-" + now.strftime("%f")[:3]

        grounded_by = draft.get("grounded_by") or []
        if isinstance(grounded_by, str):
            grounded_by = [grounded_by]

        note = Note(
            id=note_id,
            title=draft.get("title", "未命名候选"),
            content=draft.get("content", ""),
            type=NoteType.CANDIDATE,
            created=now,
            updated=now,
            gem_level=GemLevel.FLAWED.value,
            confidence=draft.get("confidence", 0.0),
            source_prompts=[prompt_id],
            grounded_by=[str(g) for g in grounded_by if g],
            knowledge_type=draft.get("knowledge_type"),
            status="pending",
        )
        if not save_note(note, add_to_index=False):
            logger.error("save_note 返回 False（prompt %s）", prompt_id)
            return None
        return note_id
    except Exception as e:
        logger.exception("创建 candidate 失败（prompt %s）: %s", prompt_id, e)
        return None


def _build_task_item(
    prompt_row: Dict[str, Any],
    context: ContextResult,
    grounding: GroundingResult,
    history: List[Dict[str, Any]],
    unresolved: List[Dict[str, Any]],
) -> Dict[str, Any]:
    """构造发给 runner 的单个 item。"""
    return {
        "prompt_id": prompt_row["prompt_id"],
        "prompt": prompt_row["prompt"],
        "context_mode": context.mode,
        "transcript": context.text,
        "permanent_evidence": [
            {"id": e["id"], "title": e["title"], "content": e["content"]}
            for e in grounding.evidence
        ],
        "prompt_history": [
            {
                "id": h["id"],
                "session_id": h["session_id"],
                "prompt": h["prompt"],
                "disposition": h.get("disposition"),
            }
            for h in history
        ],
        "unresolved_evidence": unresolved,
    }


def judge_prompts(
    kb_name: str,
    store: Optional[PromptStore] = None,
    limit: Optional[int] = None,
    session_id: Optional[str] = None,
    all_items: bool = False,
    retry_failed: bool = False,
    retry_needs_review: bool = False,
    allow_remote: bool = False,
    session_batch_limit: Optional[int] = None,
    cfg=None,
) -> JudgeReport:
    """执行一次批量判断。"""
    gm = get_global_config_manager()
    if cfg is None:
        cfg = gm.get_prompt_judge_config()
    if store is None:
        store = PromptStore()
    if session_batch_limit is None:
        session_batch_limit = cfg.session_batch_limit
    if limit is None and not all_items:
        limit = cfg.default_limit

    report = JudgeReport()

    # 1) drain spool
    from .service import drain_spool

    report.drain = drain_spool(store=store)

    # 2) 选择 prompt
    prompt_ids = _select_prompt_ids(
        store, kb_name, session_id, retry_failed, retry_needs_review, limit
    )
    if not prompt_ids:
        return report

    # 3) 按 session 分组
    prompt_rows = {}
    session_groups: Dict[str, List[int]] = {}
    for pid in prompt_ids:
        row = store.get_prompt(pid)
        if row is None:
            continue
        prompt_rows[pid] = row
        sid = row["session_id"]
        session_groups.setdefault(sid, []).append(pid)

    # 4) 逐 session 处理
    claim_token = str(uuid.uuid4())
    now = _utc_now()
    all_claimed = store.claim_prompts(kb_name, prompt_ids, claim_token, now)
    if not all_claimed:
        logger.warning("claim 全部失败（并发 judge？）")
        return report

    report.total = len(all_claimed)

    # transcript 缓存（同 session 只读一次）
    transcript_cache: Dict[str, TranscriptDocument] = {}

    for sid, pids in session_groups.items():
        s_pids = [p for p in pids if p in prompt_rows]
        if not s_pids:
            continue

        # 5) 读取 transcript（缓存）
        tp = prompt_rows[s_pids[0]].get("transcript_path")
        if sid not in transcript_cache:
            if tp:
                transcript_cache[sid] = read_transcript_safe(
                    Path(tp), allowed_roots=["~/.claude/projects"]
                )
            else:
                transcript_cache[sid] = TranscriptDocument(
                    messages=[], user_texts=[], user_indices=[]
                )
        doc = transcript_cache[sid]

        # 6) 按 batch_limit 拆分
        for batch_start in range(0, len(s_pids), session_batch_limit):
            batch_pids = s_pids[batch_start : batch_start + session_batch_limit]
            report.batches += 1

            # 7) grounding + remote consent
            first_prompt_text = prompt_rows[batch_pids[0]]["prompt"]
            grounding = fetch_judgment_grounding(
                first_prompt_text, top_k=8, max_chars=cfg.max_grounding_chars
            )
            if grounding.unavailable:
                for pid in batch_pids:
                    store.fail_judgment(kb_name, pid, f"grounding unavailable: {grounding.error}")
                    report.failed += 1
                    report.items.append(
                        {"prompt_id": pid, "status": "failed", "error": "grounding unavailable"}
                    )
                continue

            # 8) remote consent 检查
            if cfg.runner_scope == "remote" and not cfg.allow_remote and not allow_remote:
                for pid in batch_pids:
                    store.fail_judgment(kb_name, pid, "remote runner requires explicit consent")
                    report.failed += 1
                    report.items.append(
                        {"prompt_id": pid, "status": "failed", "error": "consent required"}
                    )
                continue

            # 9) 构造 task items（context + evidence）
            targets = [
                {
                    "prompt_id": pid,
                    "prompt": prompt_rows[pid]["prompt"],
                    "transcript_user_index": prompt_rows[pid].get("transcript_user_index"),
                }
                for pid in batch_pids
            ]
            context = select_context(
                doc,
                targets,
                max_transcript_chars=cfg.max_transcript_chars,
                turns_before=cfg.context_turns_before,
                turns_after=cfg.context_turns_after,
            )

            unresolved = fetch_unresolved_evidence(store, kb_name)
            task_items = []
            for pid in batch_pids:
                history = build_prompt_history(
                    store, pid, prompt_rows[pid]["session_id"], cfg.history_limit
                )
                task_items.append(
                    _build_task_item(prompt_rows[pid], context, grounding, history, unresolved)
                )

            task = {
                "schema_version": 1,
                "kb_name": kb_name,
                "items": task_items,
            }

            # 10) 调用 runner
            runner_result = run_runner(task, cfg, allow_remote=allow_remote)

            if not runner_result.ok:
                # 整个 batch 失败
                for pid in batch_pids:
                    store.fail_judgment(kb_name, pid, runner_result.error or "runner failed")
                    report.failed += 1
                    report.items.append(
                        {"prompt_id": pid, "status": "failed", "error": runner_result.error}
                    )
                continue

            # 11) 处理每个 item
            result_by_pid = {item["prompt_id"]: item for item in runner_result.items}
            for pid in batch_pids:
                item = result_by_pid.get(pid)
                if item is None:
                    store.fail_judgment(kb_name, pid, "runner missing output for this prompt")
                    report.failed += 1
                    report.items.append({"prompt_id": pid, "status": "failed", "error": "missing"})
                    continue

                candidate_id = None
                if item["classification"] == "new" and item.get("draft"):
                    candidate_id = _create_candidate_from_draft(item["draft"], pid)
                    if candidate_id is None:
                        store.fail_judgment(kb_name, pid, "candidate creation failed")
                        report.failed += 1
                        report.items.append(
                            {"prompt_id": pid, "status": "failed", "error": "candidate failed"}
                        )
                        continue

                store.finish_judgment(
                    kb_name,
                    pid,
                    classification=item["classification"],
                    reason=item.get("reason", ""),
                    confidence=item.get("confidence"),
                    matched_note_ids=item.get("matched_note_ids", []),
                    matched_prompt_ids=item.get("matched_prompt_ids", []),
                    matched_unresolved_prompt_ids=item.get("matched_unresolved_prompt_ids", []),
                    context_mode=context.mode,
                    runner_id=cfg.runner,
                    model_id=cfg.model,
                    candidate_note_id=candidate_id,
                )
                report.succeeded += 1
                report.items.append(
                    {
                        "prompt_id": pid,
                        "status": "succeeded",
                        "classification": item["classification"],
                        "candidate_id": candidate_id,
                        "context_mode": context.mode,
                    }
                )

    return report


__all__ = ["JudgeReport", "judge_prompts"]
