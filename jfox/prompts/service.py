"""Prompt 摄入编排：event → 校验 → PromptStore，spool drain，历史回填。

纯函数式（依赖注入 store/config），daemon 路由和 CLI 都直接调用。
不加载 embedding 模型，不依赖外部 LLM。
"""

import json
import logging
from pathlib import Path
from typing import Any, Dict, Optional

from ..global_config import PromptCaptureConfig, get_global_config_manager
from .store import PromptStore

logger = logging.getLogger(__name__)

# 与 fragment/internal_sources.py 保持一致；prompt-judge 是新流程 runner 标记
INTERNAL_SOURCES = frozenset({"auto-summary", "gem-synth", "prompt-judge"})


def default_spool_dir() -> Path:
    """默认 spool 路径：~/.zettelkasten/prompt-spool/。"""
    return Path.home() / ".zettelkasten" / "prompt-spool"


def _get_event_source(event: Dict[str, Any]) -> Optional[str]:
    """从 event 顶层或 metadata.source 提取来源标记（防御性解析）。"""
    if not isinstance(event, dict):
        return None
    raw = event.get("source")
    if isinstance(raw, str) and raw:
        return raw
    metadata = event.get("metadata")
    if isinstance(metadata, dict):
        raw = metadata.get("source")
        if isinstance(raw, str) and raw:
            return raw
    return None


def ingest_prompt(
    event: Dict[str, Any],
    store: Optional[PromptStore] = None,
    config: Optional[PromptCaptureConfig] = None,
    capture_id: Optional[str] = None,
) -> Dict[str, Any]:
    """处理一个 CC UserPromptSubmit event，写入 PromptStore。

    返回：
      {status: "stored"/"duplicate", prompt_id, prompt}  正常
      {status: "skipped"}                                  配置禁用 / 内部来源
      {status: "error", error}                             校验失败 / store 异常
    """
    if config is None:
        config = get_global_config_manager().get_prompt_capture_config()
    if not config.enabled:
        return {"status": "skipped"}

    if not isinstance(event, dict):
        return {"status": "error", "error": "event must be a JSON object"}

    source = _get_event_source(event)
    if source in INTERNAL_SOURCES:
        logger.debug("ingest_prompt: 跳过内部 session 来源: %s", source)
        return {"status": "skipped", "reason": f"ignored internal source: {source}"}

    if store is None:
        # daemon 端点传入常驻 store；无注入时新建（CLI drain 场景）
        store = PromptStore()

    # capture_id 优先取参数（hook 生成的 jfox_capture_id），其次 event 字段
    cid = capture_id or event.get("jfox_capture_id")
    source_key = f"capture:{cid}" if cid else None
    if not source_key:
        # 无 capture ID 时（legacy 兼容路径）用内容 hash + session 做幂等键
        import hashlib

        raw = json.dumps(
            {
                "s": event.get("session_id", ""),
                "p": event.get("prompt", ""),
                "t": event.get("transcript_path", ""),
            },
            ensure_ascii=False,
            sort_keys=True,
        )
        source_key = f"legacy:{hashlib.sha256(raw.encode('utf-8')).hexdigest()}"

    return store.insert_prompt(event, source_key=source_key, capture_id=cid)


# ---------------------------------------------------------------------------
# Spool drain
# ---------------------------------------------------------------------------


def drain_spool(
    spool_dir: Optional[Path] = None,
    store: Optional[PromptStore] = None,
) -> Dict[str, Any]:
    """扫描 spool 目录的 .json 文件，幂等导入 PromptStore。

    返回 {imported, duplicates, failed, remaining}。
    导入成功（stored 或 duplicate）后删除文件；失败文件保留供诊断。
    """
    if spool_dir is None:
        cfg = get_global_config_manager().get_prompt_capture_config()
        spool_dir = Path(cfg.spool_dir).expanduser() if cfg.spool_dir else default_spool_dir()
    spool_dir = Path(spool_dir)
    if not spool_dir.exists():
        return {"imported": 0, "duplicates": 0, "failed": 0, "remaining": 0}

    if store is None:
        store = PromptStore()

    imported = duplicates = failed = 0
    # 按文件名排序保证 drain 顺序确定（同 session 的 session_seq 稳定）
    for path in sorted(spool_dir.glob("*.json")):
        try:
            raw = path.read_text(encoding="utf-8")
            payload = json.loads(raw)
            if not isinstance(payload, dict):
                raise ValueError("spool payload is not a JSON object")
        except (json.JSONDecodeError, ValueError, OSError) as e:
            logger.warning("drain_spool: 无法解析 %s: %s", path.name, e)
            failed += 1
            continue  # 保留文件供诊断

        result = ingest_prompt(payload, store=store)
        if result["status"] in ("stored", "duplicate"):
            try:
                path.unlink()
                if result["status"] == "stored":
                    imported += 1
                else:
                    duplicates += 1
            except OSError as e:
                logger.warning("drain_spool: 删除 %s 失败: %s", path.name, e)
                failed += 1
        else:
            # error / skipped：error 保留文件，skipped 删除（内部来源无需保留）
            if result["status"] == "skipped":
                try:
                    path.unlink()
                except OSError:
                    pass
            else:
                failed += 1

    remaining = len(list(spool_dir.glob("*.json")))
    return {
        "imported": imported,
        "duplicates": duplicates,
        "failed": failed,
        "remaining": remaining,
    }


# ---------------------------------------------------------------------------
# 历史 backfill（session_fragments → user_prompts）
# ---------------------------------------------------------------------------


def backfill_from_fragments(
    store: Optional[PromptStore] = None,
    fragments_db_path: Optional[Path] = None,
    dry_run: bool = False,
) -> Dict[str, Any]:
    """从旧 session_fragments 回填 UserPromptSubmit 到 user_prompts。

    - 只读 source_event='UserPromptSubmit' 的行（不论旧 fragment_type）；
    - 从 metadata_json.prompt 读完整原文（不用截断 content）；
    - source_key = fragment:<fragment_id>，幂等可重跑；
    - 不调用 LLM、不创建 judgment、不创建 candidate；
    - dry_run=True 只统计不写入。

    返回 {found, imported, duplicates, invalid, empty}（dry_run 时 imported=0）。
    """
    import sqlite3

    from ..fragment.store import default_db_path as fragments_default_db_path

    db_path = fragments_db_path or (
        store.db_path if store is not None else fragments_default_db_path()
    )
    if store is None:
        store = PromptStore(db_path=db_path)

    imported = duplicates = invalid = empty = 0

    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(
            "SELECT fragment_id, session_id, fragment_type, timestamp, "
            "content, metadata_json FROM session_fragments "
            "WHERE source_event = 'UserPromptSubmit' ORDER BY fragment_id"
        ).fetchall()
    finally:
        conn.close()

    for row in rows:
        fid = int(row["fragment_id"])
        try:
            md = json.loads(row["metadata_json"] or "{}")
            if not isinstance(md, dict):
                md = {}
        except (json.JSONDecodeError, TypeError, ValueError):
            invalid += 1
            continue

        prompt = md.get("prompt")
        if not isinstance(prompt, str) or not prompt.strip():
            empty += 1
            continue

        event = {
            "hook_event_name": "UserPromptSubmit",
            "session_id": row["session_id"],
            "prompt": prompt,
        }
        # 保留原始 transcript_path / session_title / cwd
        for key in ("transcript_path", "session_title", "cwd"):
            if md.get(key):
                event[key] = md[key]

        if dry_run:
            # 只统计，不写入
            imported += 1
            continue
        result = store.insert_prompt(
            event,
            source_key=f"fragment:{fid}",
            source="backfill",
            source_fragment_id=fid,
            transcript_path=md.get("transcript_path"),
        )
        if result["status"] == "stored":
            imported += 1
        elif result["status"] == "duplicate":
            duplicates += 1
        else:
            invalid += 1

    return {
        "found": imported + duplicates + invalid + empty,
        "imported": 0 if dry_run else imported,
        "dry_run": dry_run,
        "duplicates": duplicates,
        "invalid": invalid,
        "empty": empty,
    }


__all__ = [
    "ingest_prompt",
    "drain_spool",
    "backfill_from_fragments",
    "default_spool_dir",
    "INTERNAL_SOURCES",
]
