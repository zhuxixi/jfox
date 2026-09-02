"""jfox prompts 子命令：记录 / 查看 / 判断 / 人工闭环。"""

import json
from typing import Optional

import typer
from rich.console import Console
from rich.table import Table

from ..global_config import get_global_config_manager

prompts_app = typer.Typer(help="记录与判断用户 prompt（gem-synth 重构）")
console = Console()


def _get_store(kb: Optional[str] = None):
    from .store import PromptStore

    if kb:
        from ..config import use_kb

        with use_kb(kb):
            return PromptStore()
    return PromptStore()


def _current_kb_name() -> str:
    from ..config import get_config

    return getattr(get_config(), "kb_name", "default")


def _kb_wrap(kb: Optional[str]):
    """返回 (kb_name, ctx)：kb 给定时返回 use_kb 上下文。"""
    if kb:
        from ..config import use_kb

        return kb, use_kb(kb)
    return _current_kb_name(), None


def _preview(text: str, max_len: int = 50) -> str:
    s = (text or "").replace("\n", " ")
    return s[: max_len - 1] + "…" if len(s) > max_len else s


# ---------------------------------------------------------------------------
# 查询类
# ---------------------------------------------------------------------------


@prompts_app.command("list")
def list_cmd(
    session: Optional[str] = typer.Option(None, "--session", help="按 session 过滤"),
    limit: int = typer.Option(20, "--limit", "-n"),
    format: str = typer.Option("table", "--format", "-f"),
    kb: Optional[str] = typer.Option(None, "--kb"),
):
    """列出已记录的 prompt（table 模式只显示截断预览）。"""
    store = _get_store(kb)
    rows = store.list_prompts(session_id=session, limit=limit)
    if format == "json":
        print(json.dumps(rows, ensure_ascii=False, indent=2))
        return
    table = Table(title=f"User Prompts（{len(rows)} 条）")
    table.add_column("ID", style="cyan")
    table.add_column("Session", style="dim")
    table.add_column("Prompt（预览）")
    table.add_column("时间", style="dim")
    for r in rows:
        table.add_row(
            str(r["prompt_id"]),
            _preview(r.get("session_id") or "", 16),
            _preview(r.get("prompt") or ""),
            (r.get("captured_at") or "")[:19],
        )
    console.print(table)


@prompts_app.command("show")
def show_cmd(
    prompt_id: int = typer.Argument(..., help="prompt ID"),
    full: bool = typer.Option(False, "--full", help="显示完整 prompt 文本"),
    format: str = typer.Option("table", "--format", "-f"),
    kb: Optional[str] = typer.Option(None, "--kb"),
):
    """查看单条 prompt 与其 judgment 详情。"""
    store = _get_store(kb)
    p = store.get_prompt(prompt_id)
    if p is None:
        console.print(f"[red]prompt {prompt_id} 不存在[/red]")
        raise typer.Exit(1)
    j = store.get_judgment(_current_kb_name() if not kb else kb, prompt_id)
    if format == "json":
        out = dict(p)
        out["judgment"] = j
        print(json.dumps(out, ensure_ascii=False, indent=2))
        return
    if full:
        console.print(p.get("prompt") or "")
    else:
        console.print(_preview(p.get("prompt") or "", 200))
    if j:
        console.print(
            f"\n[dim]judgment: {j['judgment_state']} / {j.get('classification')} "
            f"/ disposition={j['disposition']}[/dim]"
        )


@prompts_app.command("status")
def status_cmd(
    format: str = typer.Option("table", "--format", "-f"),
    kb: Optional[str] = typer.Option(None, "--kb"),
):
    """统计：总 prompt / 未判断 / 处理中 / 失败 / 待处置 / active unresolved。"""
    store = _get_store(kb)
    kb_name = kb or _current_kb_name()
    total = store.count_prompts()
    by_state = store.count_judgments_by_state(kb_name)
    pending = len(
        [
            j
            for j in store.list_judgments(kb_name, judgment_state="succeeded")
            if j["disposition"] == "pending"
        ]
    )
    active_unresolved = len(store.list_unresolved(kb_name, limit=10000))
    data = {
        "total_prompts": total,
        "unjudged": total - sum(by_state.values()),
        "processing": by_state.get("processing", 0),
        "failed": by_state.get("failed", 0),
        "succeeded": by_state.get("succeeded", 0),
        "pending_disposition": pending,
        "active_unresolved": active_unresolved,
    }
    if format == "json":
        print(json.dumps(data, ensure_ascii=False, indent=2))
        return
    table = Table(title="Prompt 状态")
    table.add_column("指标")
    table.add_column("值", justify="right")
    for k, v in data.items():
        table.add_row(k, str(v))
    console.print(table)


# ---------------------------------------------------------------------------
# 采集类
# ---------------------------------------------------------------------------


@prompts_app.command("drain")
def drain_cmd(
    format: str = typer.Option("table", "--format", "-f"),
    kb: Optional[str] = typer.Option(None, "--kb"),
):
    """把本地 spool 中未送达的 prompt 灌入数据库。"""
    from .service import drain_spool

    store = _get_store(kb)
    result = drain_spool(store=store)
    if format == "json":
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return
    console.print(
        f"drain 完成：送达 {result.get('delivered', 0)} 条，"
        f"残留 {result.get('remaining', 0)} 条"
    )


@prompts_app.command("backfill")
def backfill_cmd(
    dry_run: bool = typer.Option(False, "--dry-run"),
    format: str = typer.Option("table", "--format", "-f"),
    kb: Optional[str] = typer.Option(None, "--kb"),
):
    """从旧 session_fragments 表回填 UserPromptSubmit 历史记录。"""
    from .service import backfill_from_fragments

    store = _get_store(kb)
    result = backfill_from_fragments(store=store, dry_run=dry_run)
    if format == "json":
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return
    console.print(
        f"backfill{'（dry-run）' if dry_run else ''}："
        f"发现 {result.get('found', 0)} 条，导入 {result.get('imported', 0)} 条，"
        f"跳过 {result.get('skipped', 0)} 条"
    )


# ---------------------------------------------------------------------------
# 判断类
# ---------------------------------------------------------------------------


@prompts_app.command("judge")
def judge_cmd(
    limit: Optional[int] = typer.Option(None, "--limit", "-n"),
    session: Optional[str] = typer.Option(None, "--session"),
    all_items: bool = typer.Option(False, "--all", help="不限默认批量"),
    retry_failed: bool = typer.Option(False, "--retry-failed"),
    allow_remote: bool = typer.Option(False, "--allow-remote"),
    format: str = typer.Option("table", "--format", "-f"),
    kb: Optional[str] = typer.Option(None, "--kb"),
):
    """批量判断未处理 prompt（调用外部 runner，手动触发）。"""
    from .judge import judge_prompts

    kb_name, ctx = _kb_wrap(kb)
    import contextlib

    with ctx or contextlib.nullcontext():
        store = _get_store(kb)
        report = judge_prompts(
            kb_name,
            store=store,
            limit=limit,
            session_id=session,
            all_items=all_items,
            retry_failed=retry_failed,
            allow_remote=allow_remote,
        )
    data = {
        "total": report.total,
        "succeeded": report.succeeded,
        "failed": report.failed,
        "batches": report.batches,
        "items": report.items,
    }
    if format == "json":
        print(json.dumps(data, ensure_ascii=False, indent=2))
        return
    console.print(
        f"judge 完成：处理 {report.total} 条，"
        f"成功 {report.succeeded}，失败 {report.failed}（{report.batches} 个 batch）"
    )
    for item in report.items:
        status = item.get("status")
        pid = item.get("prompt_id")
        if status == "succeeded":
            console.print(
                f"  [green]#{pid}[/green] {item.get('classification')}"
                + (f" → candidate {item.get('candidate_id')}" if item.get("candidate_id") else "")
            )
        else:
            console.print(f"  [red]#{pid}[/red] {item.get('error', 'failed')}")


# ---------------------------------------------------------------------------
# 人工动作类
# ---------------------------------------------------------------------------


@prompts_app.command("promote")
def promote_cmd(
    prompt_id: int = typer.Argument(...),
    kb: Optional[str] = typer.Option(None, "--kb"),
):
    """promote 该 prompt 的 candidate（仅 new/pending）。"""
    from .actions import promote_prompt

    kb_name, ctx = _kb_wrap(kb)
    import contextlib

    with ctx or contextlib.nullcontext():
        store = _get_store(kb)
        ok = promote_prompt(kb_name, prompt_id, store=store)
    if not ok:
        raise typer.Exit(1)
    console.print(f"[green]prompt {prompt_id} → promoted[/green]")


@prompts_app.command("unresolved")
def unresolved_cmd(
    prompt_id: int = typer.Argument(...),
    force: bool = typer.Option(False, "--force"),
    reason: Optional[str] = typer.Option(None, "--reason"),
    kb: Optional[str] = typer.Option(None, "--kb"),
):
    """标记为待解决问题（写入清单笔记；仅 repeated，--force 可覆盖）。"""
    from .actions import unresolved_prompt

    kb_name, ctx = _kb_wrap(kb)
    import contextlib

    with ctx or contextlib.nullcontext():
        store = _get_store(kb)
        ok = unresolved_prompt(kb_name, prompt_id, store=store, force=force, reason=reason)
    if not ok:
        raise typer.Exit(1)
    console.print(f"[yellow]prompt {prompt_id} → unresolved[/yellow]")


@prompts_app.command("resolve-unresolved")
def resolve_unresolved_cmd(
    prompt_id: int = typer.Argument(...),
    reason: Optional[str] = typer.Option(None, "--reason"),
    kb: Optional[str] = typer.Option(None, "--kb"),
):
    """解决一个待解决问题（移除清单标记）。"""
    from .actions import resolve_unresolved_prompt

    kb_name, ctx = _kb_wrap(kb)
    import contextlib

    with ctx or contextlib.nullcontext():
        store = _get_store(kb)
        ok = resolve_unresolved_prompt(kb_name, prompt_id, reason=reason, store=store)
    if not ok:
        raise typer.Exit(1)
    console.print(f"[green]prompt {prompt_id} → resolved[/green]")


@prompts_app.command("ignore")
def ignore_cmd(
    prompt_id: int = typer.Argument(...),
    reject_candidate: bool = typer.Option(
        False, "--reject-candidate", help="同时 reject 已有 candidate"
    ),
    kb: Optional[str] = typer.Option(None, "--kb"),
):
    """忽略该 prompt（有 candidate 时需 --reject-candidate）。"""
    from .actions import ignore_prompt

    kb_name, ctx = _kb_wrap(kb)
    import contextlib

    with ctx or contextlib.nullcontext():
        store = _get_store(kb)
        ok = ignore_prompt(kb_name, prompt_id, store=store, reject_candidate=reject_candidate)
    if not ok:
        raise typer.Exit(1)
    console.print(f"[dim]prompt {prompt_id} → ignored[/dim]")


@prompts_app.command("retry")
def retry_cmd(
    prompt_id: int = typer.Argument(...),
    kb: Optional[str] = typer.Option(None, "--kb"),
):
    """重置 failed/needs_review judgment，允许重新判断。"""
    from .actions import retry_prompt

    kb_name, ctx = _kb_wrap(kb)
    import contextlib

    with ctx or contextlib.nullcontext():
        store = _get_store(kb)
        ok = retry_prompt(kb_name, prompt_id, store=store)
    if not ok:
        raise typer.Exit(1)
    console.print(f"prompt {prompt_id} 已重置，下次 judge 将重新处理")


# ---------------------------------------------------------------------------
# 配置
# ---------------------------------------------------------------------------


@prompts_app.command("config")
def config_cmd(
    set_key: Optional[str] = typer.Option(None, "--set", help="设置配置项 key=value"),
    format: str = typer.Option("table", "--format", "-f"),
):
    """查看/设置 prompt 采集与判断配置。"""
    gm = get_global_config_manager()
    if set_key:
        if "=" not in set_key:
            console.print("[red]--set 需要 key=value 格式[/red]")
            raise typer.Exit(1)
        key, _, value = set_key.partition("=")
        # 数值字段自动转换
        if value.isdigit():
            value = int(value)
        elif value.lower() in ("true", "false"):
            value = value.lower() == "true"
        # 尝试 judge 配置，再尝试 capture 配置
        judge_fields = {
            f.name for f in __import__("dataclasses").fields(type(gm.get_prompt_judge_config()))
        }
        if key in judge_fields:
            ok = gm.update_prompt_judge_config(**{key: value})
        else:
            ok = gm.update_prompt_capture_config(**{key: value})
        if not ok:
            console.print(f"[red]设置失败：{key}[/red]")
            raise typer.Exit(1)
        console.print(f"[green]{key} = {value}[/green]")
        return

    capture = gm.get_prompt_capture_config()
    judge = gm.get_prompt_judge_config()
    import dataclasses

    data = {
        "capture": dataclasses.asdict(capture),
        "judge": dataclasses.asdict(judge),
    }
    if format == "json":
        print(json.dumps(data, ensure_ascii=False, indent=2, default=str))
        return
    table = Table(title="Prompts 配置")
    table.add_column("模块")
    table.add_column("配置项")
    table.add_column("值")
    for section, cfg_dict in data.items():
        for k, v in cfg_dict.items():
            table.add_row(section, k, str(v))
    console.print(table)
