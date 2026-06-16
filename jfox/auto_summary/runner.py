"""
auto-summary 的核心：调用 claude -p 生成结构化摘要并写入 jfox 知识库。

run_once(): 同步执行一轮扫描 + 总结，返回处理报告
scan_pending(): 仅返回待处理 session（dry-run）
summarize_one(): 处理单个 session（供 CLI 单条触发或测试）
"""

from __future__ import annotations

import json
import logging
import os
import re
import shutil
import subprocess
import threading
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Optional

from ..global_config import AutoSummaryConfig, get_global_config_manager
from .ledger import Ledger, SessionStatus
from .scanner import (
    DEFAULT_PROJECT_BLOCKLIST_SUBSTRINGS,
    SessionFile,
    default_claude_projects_dir,
    is_running_inside_isolated_dir,
    isolated_runs_dir,
)
from .sources import (
    extract_dialog_for,
    get_sources,
    session_key,
)

logger = logging.getLogger(__name__)


SYSTEM_PROMPT = """你是知识库归档助手。我会通过用户消息提供一段 Claude Code 会话的对话记录（可能被截断）。

你的任务：阅读对话并输出一个**单一的 JSON 对象**，描述这次会话的内容。

强约束：
1. 输出**必须**是合法 JSON，不要 Markdown 围栏、不要任何前后说明文字
2. 不允许调用任何工具，仅做纯文本生成
3. 字段：
   - skip (bool): 仅当对话内容很少 / 无实质工作 / 仅做闲聊或试探时设 true
   - reason (str): 当 skip=true 时填跳过原因，否则空串
   - title (str): 该会话的概括标题，<= 50 个汉字。中文。
   - topic (str): 简短主题词，例如 "auto-summary 设计" 或 "PR #220 review"。中文。
   - summary_md (str): Markdown 正文，包含五个二级章节：
       ## 背景
       <本次会话的目标 / 起点状态>
       ## 做了什么
       <要点列表，每点可含 1-2 句技术细节或涉及的文件/命令>
       ## 关键决策
       <要点列表，每点含决策与理由>
       ## 技术细节
       <关键文件路径 / 代码片段 / 配置等可复用的上下文>
       ## 未决事项
       <要点列表，没有则写 "无">
     正文中文，保留足够上下文使其可独立读懂，但避免冗长。
   - tags (list[str]): 3-6 个标签，小写英文或中文短词，不带 # 号
4. JSON 字段顺序无要求，但所有字段必须出现"""


class SummaryOutcome(str, Enum):
    SUCCESS = "success"
    SKIPPED = "skipped"
    FAILED = "failed"  # transient
    FAILED_PERMANENT = "failed_permanent"


@dataclass
class SummaryResult:
    """summarize_one 的返回"""

    session_id: str
    outcome: SummaryOutcome
    note_id: Optional[str] = None
    title: Optional[str] = None
    reason: Optional[str] = None  # skip / failure 原因
    error: Optional[str] = None


@dataclass
class RunReport:
    """一轮 run_once 的总报告"""

    scanned: int = 0  # 扫描到的候选 session 数（已过滤 ledger）
    processed: int = 0  # 实际尝试 summarize 的数量
    success: int = 0
    skipped: int = 0
    failed: int = 0
    items: list[SummaryResult] = field(default_factory=list)


# =============================================================================
# 主入口
# =============================================================================


def scan_pending(
    cfg: Optional[AutoSummaryConfig] = None,
    claude_projects_dir: Optional[Path] = None,
    ledger: Optional[Ledger] = None,
) -> list[SessionFile]:
    """返回当前会被 run_once 处理的 session 列表（已过滤 ledger 中已了结的）

    通过 get_sources(cfg) 汇总所有启用的来源（claude / kimi），逐个迭代并按
    ``{source}:{session_id}`` 前缀去重。
    注意：``claude_projects_dir`` 参数仅为向后兼容保留，不再生效（来源由配置决定）。
    """
    del claude_projects_dir  # 向后兼容：忽略
    cfg = cfg or get_global_config_manager().get_auto_summary_config()
    ledger = ledger if ledger is not None else Ledger()

    pending: list[SessionFile] = []
    for source in get_sources(cfg):
        for sf in source.iter_sessions(cfg):
            if ledger.is_done(session_key(sf)):
                continue
            pending.append(sf)
    return pending


def run_once(
    cfg: Optional[AutoSummaryConfig] = None,
    claude_projects_dir: Optional[Path] = None,
    ledger: Optional[Ledger] = None,
    dry_run: bool = False,
) -> RunReport:
    """
    同步执行一轮扫描 + 总结。

    daemon 后台循环和 CLI `auto-summary run` 都通过这个函数。
    返回 RunReport；失败的单个 session 不会让整轮中断。
    """
    cfg = cfg or get_global_config_manager().get_auto_summary_config()
    ledger = ledger if ledger is not None else Ledger()

    if is_running_inside_isolated_dir():
        logger.info("当前 cwd 在 auto-summary 隔离目录内，跳过本轮以避免递归")
        return RunReport()

    pending = scan_pending(cfg=cfg, claude_projects_dir=claude_projects_dir, ledger=ledger)
    report = RunReport(scanned=len(pending))

    if dry_run or not pending:
        return report

    limit = max(1, cfg.max_per_tick)
    for sf in pending[:limit]:
        result = summarize_one(sf, cfg=cfg, ledger=ledger)
        report.items.append(result)
        report.processed += 1
        if result.outcome == SummaryOutcome.SUCCESS:
            report.success += 1
        elif result.outcome == SummaryOutcome.SKIPPED:
            report.skipped += 1
        else:
            report.failed += 1

    return report


def summarize_one(
    session_file: SessionFile,
    cfg: Optional[AutoSummaryConfig] = None,
    ledger: Optional[Ledger] = None,
) -> SummaryResult:
    """处理单个 session 文件，写入笔记并更新 ledger"""
    cfg = cfg or get_global_config_manager().get_auto_summary_config()
    ledger = ledger if ledger is not None else Ledger()
    project = session_file.project_dir_name

    # 1) 抽对话
    extracted = extract_dialog_for(session_file, cfg)
    if not extracted.dialog_text or extracted.user_turn_count == 0:
        ledger.record_skip(session_key(session_file), project, "no user content")
        return SummaryResult(
            session_id=session_file.session_id,
            outcome=SummaryOutcome.SKIPPED,
            reason="no user content",
        )

    # 2) 调 claude -p
    try:
        claude_output = _invoke_claude(
            extracted_dialog_text=_build_user_prompt(session_file, extracted), cfg=cfg
        )
    except _ClaudeNotFound as e:
        logger.exception("claude 二进制定位失败 session=%s", session_file.session_id)
        ledger.record_failure(session_key(session_file), project, str(e))
        return SummaryResult(
            session_id=session_file.session_id,
            outcome=_failed_outcome(ledger, session_key(session_file)),
            error=str(e),
        )
    except _ClaudeInvocationError as e:
        logger.exception("claude -p 调用失败 session=%s", session_file.session_id)
        ledger.record_failure(session_key(session_file), project, str(e))
        return SummaryResult(
            session_id=session_file.session_id,
            outcome=_failed_outcome(ledger, session_key(session_file)),
            error=str(e),
        )

    # 3) 解析 claude 返回的 JSON
    try:
        parsed = _parse_claude_json(claude_output)
    except _ParseError as e:
        logger.warning(
            "解析 claude 输出失败 session=%s err=%s preview=%r",
            session_file.session_id,
            e,
            claude_output[:300],
        )
        ledger.record_failure(session_key(session_file), project, f"parse error: {e}")
        return SummaryResult(
            session_id=session_file.session_id,
            outcome=_failed_outcome(ledger, session_key(session_file)),
            error=f"parse error: {e}",
        )

    # 4) skip 分支
    if parsed.get("skip") is True:
        reason = str(parsed.get("reason") or "claude marked skip")
        ledger.record_skip(session_key(session_file), project, reason)
        return SummaryResult(
            session_id=session_file.session_id,
            outcome=SummaryOutcome.SKIPPED,
            reason=reason,
        )

    # 5) 写入知识库
    title = (parsed.get("title") or "").strip() or f"会话 {session_file.session_id[:8]}"
    topic = (parsed.get("topic") or "").strip() or "claude-code-session"
    summary_md = (parsed.get("summary_md") or "").strip()
    tags = parsed.get("tags") or []
    if not isinstance(tags, list):
        tags = []
    tags = [str(t).strip() for t in tags if str(t).strip()]
    base_tags = ["session", "auto-summary"]
    for bt in base_tags:
        if bt not in tags:
            tags.append(bt)

    if not summary_md:
        ledger.record_failure(session_key(session_file), project, "empty summary_md")
        return SummaryResult(
            session_id=session_file.session_id,
            outcome=_failed_outcome(ledger, session_key(session_file)),
            error="claude 返回的 summary_md 为空",
        )

    full_content = _compose_note_body(extracted, summary_md, session_file)

    try:
        note_id = _save_session_note(
            content=full_content,
            title=title,
            tags=tags,
            topic=topic,
            target_kb=cfg.target_kb,
        )
    except Exception as e:
        logger.exception("保存会话笔记失败 session=%s", session_file.session_id)
        ledger.record_failure(session_key(session_file), project, f"save error: {e}")
        return SummaryResult(
            session_id=session_file.session_id,
            outcome=_failed_outcome(ledger, session_key(session_file)),
            error=f"save error: {e}",
        )

    ledger.record_success(session_key(session_file), project, note_id)
    return SummaryResult(
        session_id=session_file.session_id,
        outcome=SummaryOutcome.SUCCESS,
        note_id=note_id,
        title=title,
    )


# =============================================================================
# 内部：claude 调用
# =============================================================================


class _ClaudeNotFound(RuntimeError):
    pass


class _ClaudeInvocationError(RuntimeError):
    pass


class _ParseError(ValueError):
    pass


def _resolve_claude_binary(cfg: AutoSummaryConfig) -> str:
    """返回 claude 可执行文件的绝对路径"""
    if cfg.claude_binary:
        candidate = Path(cfg.claude_binary).expanduser().resolve()
        if candidate.is_file():
            return str(candidate)
        resolved = shutil.which(str(candidate))
        if resolved:
            return resolved
        raise _ClaudeNotFound(
            f"配置的 claude_binary 不可执行: {cfg.claude_binary} (展开后: {candidate})"
        )

    resolved = shutil.which("claude")
    if not resolved:
        raise _ClaudeNotFound(
            "未找到 'claude' 命令。请确认已安装 Claude Code CLI 并在 PATH 中，"
            "或在配置中显式设置 claude_binary。"
        )
    return resolved


def _build_user_prompt(session_file: SessionFile, extracted) -> str:
    """构造给 claude -p 的 stdin 输入：metadata 头 + dialog 正文"""
    lines = [
        "# Claude Code 会话摘要请求",
        "",
        f"- session_id: {session_file.session_id}",
        f"- project_dir: {session_file.project_dir_name}",
    ]
    if extracted.cwd:
        lines.append(f"- cwd: {extracted.cwd}")
    if extracted.git_branch:
        lines.append(f"- git_branch: {extracted.git_branch}")
    if extracted.started_at:
        lines.append(f"- started_at: {extracted.started_at}")
    if extracted.ended_at:
        lines.append(f"- ended_at: {extracted.ended_at}")
    lines.append(
        f"- 用户轮次: {extracted.user_turn_count}, 助手轮次: {extracted.assistant_turn_count}"
    )
    if extracted.truncated:
        lines.append("- 注意：对话过长，已截断中段")
    lines.append("")
    lines.append("# 对话记录")
    lines.append("")
    lines.append(extracted.dialog_text)
    lines.append("")
    lines.append("---")
    lines.append("现在请按 system prompt 要求输出 JSON。")
    return "\n".join(lines)


def _run_claude(
    cmd: list[str],
    input_text: str,
    timeout: int,
    cwd: str,
    env: dict[str, str],
    shell: bool = False,
    stop_event: Optional[threading.Event] = None,
) -> str:
    """执行子命令，支持 stop_event 中断。

    使用 Popen + 轮询代替 subprocess.run，使 stop_event.set() 能在 ~1s 内
    终止子进程，而非等待整个 timeout。
    """
    import time as _time

    proc = subprocess.Popen(
        cmd,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
        cwd=cwd,
        env=env,
        shell=shell,
    )

    # 后台线程读取 stderr，防止管道缓冲区满导致死锁
    stderr_chunks: list[str] = []
    stderr_thread = threading.Thread(
        target=lambda: stderr_chunks.append(proc.stderr.read()),
        daemon=True,
    )
    stderr_thread.start()

    try:
        if input_text:
            proc.stdin.write(input_text)
        proc.stdin.close()
    except (BrokenPipeError, OSError) as e:
        logger.warning("子进程 stdin 写入失败（进程可能已提前退出）: %s", e)

    try:
        deadline = _time.monotonic() + timeout
        while _time.monotonic() < deadline:
            if stop_event and stop_event.is_set():
                proc.terminate()
                try:
                    proc.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    proc.kill()
                    proc.wait()
                raise RuntimeError("Claude subprocess interrupted by stop signal")

            if proc.poll() is not None:
                break
            _time.sleep(1)

        if proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait()
            raise TimeoutError(f"Subprocess timed out after {timeout}s")

        stderr_thread.join(timeout=5)
        stderr_text = "".join(stderr_chunks)

        if proc.returncode != 0:
            stderr = stderr_text.strip()[:500]
            raise RuntimeError(f"Subprocess exited {proc.returncode}: {stderr or '(no stderr)'}")

        out = (proc.stdout.read() or "").strip()
        if not out:
            stderr_hint = stderr_text.strip()[:200]
            raise RuntimeError(f"Empty stdout (stderr: {stderr_hint or '(none)'})")
        return out
    except Exception:
        if proc.poll() is None:
            proc.kill()
            proc.wait()
        raise


def _invoke_claude(extracted_dialog_text: str, cfg: AutoSummaryConfig) -> str:
    """调用 claude -p，返回原始 stdout（非空字符串）"""
    binary = _resolve_claude_binary(cfg)
    cwd = isolated_runs_dir()

    cmd = [
        binary,
        "-p",
        "--output-format",
        "json",
        "--append-system-prompt",
        SYSTEM_PROMPT,
        "--permission-mode",
        "bypassPermissions",
    ]

    # Windows 下对 .cmd 要走 shell 解释（shutil.which 可能返回 .cmd 路径）
    use_shell = os.name == "nt" and binary.lower().endswith((".cmd", ".bat"))

    # 隔离环境：避免继承 JFOX_KB / JFOX_DAEMON_PROCESS 等可能影响子 claude 行为的变量
    env = os.environ.copy()
    for noisy in ("JFOX_KB", "JFOX_DAEMON_PROCESS"):
        env.pop(noisy, None)

    stop_event = getattr(cfg, "_stop_event", None)

    try:
        return _run_claude(
            cmd=cmd,
            input_text=extracted_dialog_text,
            timeout=max(30, cfg.claude_timeout_seconds),
            cwd=str(cwd),
            env=env,
            shell=use_shell,
            stop_event=stop_event,
        )
    except TimeoutError as e:
        raise _ClaudeInvocationError(f"claude -p 超时（{cfg.claude_timeout_seconds}s）") from e
    except RuntimeError as e:
        msg = str(e)
        if "interrupted" in msg.lower():
            raise
        if "exited" in msg or "Empty stdout" in msg:
            raise _ClaudeInvocationError(msg) from e
        raise
    except OSError as e:
        raise _ClaudeInvocationError(f"启动 claude 失败: {e}") from e


def _parse_claude_json(stdout: str) -> dict[str, Any]:
    """
    claude -p --output-format json 的外层封装格式可能含有 'result' 字段，
    其内才是模型的真实输出。这里先剥外壳再找内层 JSON。
    """
    # 第一层：claude CLI 的 JSON envelope
    inner_text: Optional[str] = None
    try:
        envelope = json.loads(stdout)
        if isinstance(envelope, dict):
            for key in ("result", "text", "content", "response"):
                v = envelope.get(key)
                if isinstance(v, str) and v.strip():
                    inner_text = v
                    break
            # 如果外层就是我们要的 JSON 对象（直接含 title/summary_md），返回即可
            if inner_text is None and any(k in envelope for k in ("summary_md", "title", "skip")):
                return envelope
    except json.JSONDecodeError:
        # 不是 JSON 包装，可能 claude 直接吐了模型输出
        inner_text = stdout

    if inner_text is None:
        raise _ParseError("未从 claude 输出中找到内层文本")

    return _extract_object(inner_text)


def _extract_balanced_json(text: str, start: int) -> Optional[str]:
    """从 text[start] 处（必须是 '{'）开始，找到配对的 '}' 返回子串。

    正确处理字符串内的转义引号和嵌套大括号。"""
    depth = 0
    in_string = False
    escape = False
    for i in range(start, len(text)):
        ch = text[i]
        if in_string:
            if escape:
                escape = False
            elif ch == "\\":
                escape = True
            elif ch == '"':
                in_string = False
        else:
            if ch == '"':
                in_string = True
            elif ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    return text[start : i + 1]
    return None


def _extract_object(text: str) -> dict[str, Any]:
    """从可能含有 markdown 围栏或前后说明的字符串里抠出第一个 JSON 对象"""
    text = text.strip()
    if not text:
        raise _ParseError("空文本")

    # 直接尝试
    try:
        obj = json.loads(text)
        if isinstance(obj, dict):
            return obj
    except json.JSONDecodeError:
        pass

    # 剥 ```json fences```
    fenced = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
    if fenced:
        try:
            obj = json.loads(fenced.group(1))
            if isinstance(obj, dict):
                return obj
        except json.JSONDecodeError:
            pass

    # 找第一个平衡的大括号对象（不用贪婪正则，避免跨对象匹配）
    brace_idx = text.find("{")
    if brace_idx >= 0:
        candidate = _extract_balanced_json(text, brace_idx)
        if candidate is not None:
            try:
                obj = json.loads(candidate)
                if isinstance(obj, dict):
                    return obj
            except json.JSONDecodeError as e:
                raise _ParseError(f"找到了 {{...}} 但无法解析: {e}") from e

    raise _ParseError("文本中找不到 JSON 对象")


# =============================================================================
# 内部：写入知识库
# =============================================================================


def _compose_note_body(extracted, summary_md: str, sf: SessionFile) -> str:
    """拼装最终笔记 Markdown 正文，附带元数据 footer"""
    meta_lines = ["---", "## 元数据", ""]
    if extracted.cwd:
        meta_lines.append(f"- 工作目录: `{extracted.cwd}`")
    if extracted.git_branch:
        meta_lines.append(f"- Git 分支: `{extracted.git_branch}`")
    if extracted.started_at:
        meta_lines.append(f"- 起始时间: {extracted.started_at}")
    if extracted.ended_at:
        meta_lines.append(f"- 结束时间: {extracted.ended_at}")
    meta_lines.append(
        f"- 对话轮次: 用户 {extracted.user_turn_count} / 助手 {extracted.assistant_turn_count}"
    )
    meta_lines.append(f"- session_id: `{sf.session_id}`")
    meta_lines.append(f"- 项目目录: `{sf.project_dir_name}`")
    meta_lines.append("- 来源: jfox auto-summary")
    return summary_md.strip() + "\n\n" + "\n".join(meta_lines)


def _save_session_note(
    content: str,
    title: str,
    tags: list[str],
    topic: str,
    target_kb: Optional[str],
) -> str:
    """
    在指定 KB 内创建一条 session 类型笔记，返回 note_id。

    不复用 cli._add_note_impl 是为了避免它的 print 输出污染 daemon 日志。
    """
    # 延迟导入，避免循环 / 加载成本
    from .. import note as note_module
    from ..config import use_kb
    from ..models import NoteType

    with use_kb(target_kb):
        new_note = note_module.create_note(
            content=content,
            title=title,
            note_type=NoteType.SESSION,
            tags=tags,
            links=[],
            source=None,
            topic=topic,
        )
        if not note_module.save_note(new_note):
            raise RuntimeError("note_module.save_note 返回 False")
        return new_note.id


def _failed_outcome(ledger: Ledger, session_id: str) -> SummaryOutcome:
    """根据 ledger 中最新状态返回 transient or permanent"""
    entry = ledger.get(session_id)
    if entry is None:
        return SummaryOutcome.FAILED
    if entry.status == SessionStatus.FAILED_PERMANENT.value:
        return SummaryOutcome.FAILED_PERMANENT
    return SummaryOutcome.FAILED


# Re-export
__all__ = [
    "SummaryOutcome",
    "SummaryResult",
    "RunReport",
    "scan_pending",
    "run_once",
    "summarize_one",
    "DEFAULT_PROJECT_BLOCKLIST_SUBSTRINGS",
    "default_claude_projects_dir",
]
