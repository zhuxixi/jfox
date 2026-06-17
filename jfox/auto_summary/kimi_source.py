"""
Kimi Code session 来源：扫描 ~/.kimi-code/sessions/wd_*/session_*/agents/main/wire.jsonl，
解析 wire 协议提取对话。
"""

from __future__ import annotations

import json
import logging
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator, Optional

from ..global_config import AutoSummaryConfig
from .extractor import DEFAULT_MAX_DIALOG_CHARS, ExtractedDialog, _truncate
from .scanner import SessionFile

logger = logging.getLogger(__name__)


def _ms_to_iso(ms: int) -> Optional[str]:
    """毫秒级 epoch → ISO8601 字符串（UTC）"""
    try:
        return datetime.fromtimestamp(ms / 1000, tz=timezone.utc).isoformat()
    except (TypeError, ValueError, OSError, OverflowError):
        return None


def _flatten_text(content) -> str:
    """Kimi content: [{type:text,text:...}, ...] → 纯文本"""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for item in content:
            if isinstance(item, dict) and item.get("type") == "text":
                t = item.get("text")
                if isinstance(t, str) and t.strip():
                    parts.append(t)
        return "\n".join(parts)
    return ""


def _find_cwd(record: dict) -> Optional[str]:
    """在 loop_event 记录里递归找 cwd 字段（cwd 嵌在 event 子对象里）。

    带深度限制（默认 20 层），防止病态嵌套记录触发 RecursionError。
    """

    def _walk(o, depth: int = 0):
        if depth > 20:
            return None
        if isinstance(o, dict):
            cwd = o.get("cwd")
            if isinstance(cwd, str) and cwd:
                return cwd
            for v in o.values():
                r = _walk(v, depth + 1)
                if r:
                    return r
        elif isinstance(o, list):
            for v in o:
                r = _walk(v, depth + 1)
                if r:
                    return r
        return None

    return _walk(record)


class KimiCodeSource:
    """Kimi Code session 来源：扫描 wire.jsonl 并解析 wire 协议。"""

    name = "kimi"

    def __init__(self, kimi_dir: Path):
        self.kimi_dir = kimi_dir

    def iter_sessions(self, cfg: AutoSummaryConfig) -> Iterator[SessionFile]:
        """遍历 kimi_dir/wd_*/session_*/agents/main/wire.jsonl，按 mtime/size 过滤。"""
        if not self.kimi_dir.is_dir():
            return

        now = time.time()
        idle_sec = max(0, cfg.idle_threshold_minutes) * 60
        min_size = max(0, cfg.min_session_size_kb) * 1024
        max_size = max(0, cfg.max_session_size_mb) * 1024 * 1024
        skip_sec = max(0, cfg.skip_after_days) * 86400

        try:
            wd_entries = sorted(self.kimi_dir.iterdir())
        except OSError as e:
            logger.debug("无法遍历 kimi_dir %s: %s", self.kimi_dir, e)
            return
        for wd in wd_entries:
            if not wd.is_dir() or not wd.name.startswith("wd_"):
                continue
            try:
                sess_entries = sorted(wd.iterdir())
            except OSError as e:
                logger.debug("无法遍历 %s: %s", wd, e)
                continue
            for sess in sess_entries:
                if not sess.is_dir() or not sess.name.startswith("session_"):
                    continue
                sid = sess.name[len("session_") :]
                if not sid:
                    continue
                wire = sess / "agents" / "main" / "wire.jsonl"
                if not wire.is_file():
                    continue
                try:
                    stat = wire.stat()
                except OSError as e:
                    logger.debug("无法 stat %s: %s", wire, e)
                    continue
                size, mtime = stat.st_size, stat.st_mtime
                age = now - mtime
                if size < min_size:
                    continue
                if max_size and size > max_size:
                    logger.debug("跳过过大 kimi session %s", wire)
                    continue
                if age < idle_sec:
                    continue
                if skip_sec and age > skip_sec:
                    continue
                yield SessionFile(
                    session_id=sid,
                    project_dir_name=wd.name,
                    path=wire,
                    mtime=mtime,
                    size_bytes=size,
                    source="kimi",
                )

    def extract_dialog(self, sf: SessionFile) -> ExtractedDialog:
        """解析单个 kimi wire.jsonl + 同目录三级的 state.json → ExtractedDialog。

        与 Claude 的 extractor 返回结构一致，runner 下游可无差别处理。
        """
        result = ExtractedDialog()
        result.project_dir_name = sf.project_dir_name

        session_dir = sf.path.parent.parent.parent  # wire.jsonl → main → agents → session_<uuid>
        self._read_state(session_dir / "state.json", result)

        turns: list[str] = []
        cwd: Optional[str] = None
        first_time: Optional[int] = None
        last_time: Optional[int] = None

        try:
            with open(sf.path, "r", encoding="utf-8", errors="replace") as f:
                for raw in f:
                    raw = raw.strip()
                    if not raw:
                        continue
                    try:
                        rec = json.loads(raw)
                    except json.JSONDecodeError:
                        continue
                    if not isinstance(rec, dict):
                        continue
                    t = rec.get("type")
                    if isinstance(rec.get("time"), int):
                        if first_time is None:
                            first_time = rec["time"]
                        last_time = rec["time"]

                    if t == "context.append_loop_event" and cwd is None:
                        cwd = _find_cwd(rec)
                    elif t == "context.append_message":
                        msg = rec.get("message") if isinstance(rec.get("message"), dict) else {}
                        role = msg.get("role") or "user"
                        text = _flatten_text(msg.get("content")).strip()
                        if not text:
                            continue
                        turns.append(f"## {role}\n\n{text}")
                        if role == "user":
                            result.user_turn_count += 1
                        elif role == "assistant":
                            result.assistant_turn_count += 1
                    # turn.prompt 不单独处理：Kimi 协议中它总伴随同文本的
                    # context.append_message(role=user)，append_message 已记录该输入；
                    # 单独处理会重复 append+计数翻倍（issue-1），而用全局 set 去重又会
                    # 误杀不同轮次的相同短文本如"继续"/"ok"（issue-6）。故依赖 append_message 独占。
        except OSError as e:
            logger.warning("读取 kimi session 失败 %s: %s", sf.path, e)

        result.cwd = cwd
        # 与 Claude 路径一致：超长对话截断到 DEFAULT_MAX_DIALOG_CHARS，置 truncated 标记
        dialog_text, result.truncated = _truncate(
            "\n\n---\n\n".join(turns), DEFAULT_MAX_DIALOG_CHARS
        )
        result.dialog_text = dialog_text

        # 时间戳降级：state.json 没给则从 wire time(毫秒)推导
        if result.started_at is None and first_time is not None:
            result.started_at = _ms_to_iso(first_time)
        if result.ended_at is None and last_time is not None:
            result.ended_at = _ms_to_iso(last_time)
        return result

    @staticmethod
    def _read_state(state_path: Path, result: ExtractedDialog) -> None:
        """读 session_<uuid>/state.json 的 createdAt/updatedAt 写入 result。"""
        if not state_path.is_file():
            return
        try:
            with open(state_path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except (OSError, json.JSONDecodeError, UnicodeDecodeError) as e:
            logger.debug("state.json 读取失败 %s: %s", state_path, e)
            return
        if isinstance(data, dict):
            if isinstance(data.get("createdAt"), str):
                result.started_at = data["createdAt"]
            if isinstance(data.get("updatedAt"), str):
                result.ended_at = data["updatedAt"]
