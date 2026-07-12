"""CLI 子命令组：jfox candidates list / show"""

from __future__ import annotations

import json as _json
from typing import Optional

import typer
from rich.console import Console
from rich.table import Table

# 表格/错误用带颜色的 console；JSON 用 typer.echo 直接输出（避免 Rich 对 \n 二次转义）
console = Console(legacy_windows=False)

candidates_app = typer.Typer(
    name="candidates",
    help="查看 L3 合成的候选知识宝石（破损级，待 L5 审阅）",
    no_args_is_help=True,
)


@candidates_app.command("show")
def show_cmd(
    note_id: str = typer.Argument(..., help="candidate 笔记 ID"),
    kb: Optional[str] = typer.Option(None, "--kb", "-k", help="目标知识库名称"),
    output_format: str = typer.Option(
        "markdown", "--format", "-f", help="输出格式: markdown, json"
    ),
) -> None:
    """查看 candidate 笔记详情（完整 frontmatter + 正文，不截断）"""
    from ..config import use_kb
    from ..note import load_note_by_id

    with use_kb(kb):
        try:
            note = load_note_by_id(note_id)
        except Exception as e:
            # --format json 时输出结构化错误（AGENTS.md 约定），否则打印红色提示
            if output_format == "json":
                typer.echo(_json.dumps({"success": False, "error": str(e)}, ensure_ascii=False))
            else:
                console.print(f"[red]读取 candidate 失败：{e}[/red]")
            raise typer.Exit(code=1)
        if note is None:
            # 与 except 分支一致：--format json 时输出结构化错误，否则打印红色提示
            if output_format == "json":
                typer.echo(
                    _json.dumps(
                        {"success": False, "error": f"找不到笔记 ID={note_id}"},
                        ensure_ascii=False,
                    )
                )
            else:
                console.print(f"[red]找不到笔记 ID={note_id}[/red]")
            raise typer.Exit(code=1)

        if output_format == "json":
            # content 字段用纯正文（note.content），不含 frontmatter（避免与 top-level
            # 字段重复）。to_dict() 会把 content 截断到 200 字符，这里用完整正文覆盖。
            data = note.to_dict()
            data["content"] = note.content
            # 用 typer.echo 直接输出，避免 Rich console 对 \n 二次转义（破坏 JSON）
            typer.echo(_json.dumps(data, ensure_ascii=False, indent=2))
            return

        # 默认输出完整原始 markdown（与 jfox show 一致）。
        # 用 typer.echo 而非 console.print：Rich 会解析正文中的 [xxx] 标记（如笔记里的
        # [链接]、[red] 等字面量）当成 markup/颜色标签，导致输出错乱或丢失字面量。
        try:
            typer.echo(note.filepath.read_text(encoding="utf-8"))
        except Exception as e:
            # 文件读取失败时回退到内存中的 markdown 表示（同样用 typer.echo 避免 markup）
            console.print(f"[yellow]读取文件失败，使用内存表示：{e}[/yellow]")
            typer.echo(note.to_markdown())


@candidates_app.command("list")
def list_cmd(
    status: str = typer.Option(
        "pending",
        "--status",
        help="按 status 过滤 (pending/rejected/all；promoted 笔记已转 permanent，用 list --type permanent 查看)",
    ),
    min_confidence: float = typer.Option(0.0, "--min-confidence", help="最低置信度"),
    limit: int = typer.Option(50, "--limit", "-n"),
    output_format: str = typer.Option("table", "--format", "-f", help="table, json"),
    kb: Optional[str] = typer.Option(None, "--kb", "-k", help="目标知识库名称"),
) -> None:
    """列出 candidate 笔记"""
    from ..config import use_kb
    from ..models import NoteType
    from ..note import list_notes

    # 非正 --limit（0 或负值）回退默认，避免 fetch_limit 变 0 拉不到数据
    if limit < 1:
        limit = 50

    with use_kb(kb):
        # 多取一些再在内存里按 status/confidence 过滤（这些字段在 frontmatter，索引层不过滤）
        # limit 经上面 clamp 必 >= 1，直接 limit*3（原 `if limit > 0 else limit` 分支已死）
        try:
            # rejected candidate 已 archived，默认 exclude_archived 会漏掉——按需包含
            notes = list_notes(
                note_type=NoteType.CANDIDATE,
                limit=limit * 3,
                include_archived=status in ("rejected", "all"),
            )
        except Exception as e:
            # 未初始化/空库应返回空列表而非抛错；真正读取失败才报错退出
            # --format json 时输出结构化错误（AGENTS.md 约定），否则打印红色提示
            if output_format == "json":
                typer.echo(_json.dumps({"success": False, "error": str(e)}, ensure_ascii=False))
            else:
                console.print(f"[red]读取 candidate 失败：{e}[/red]")
            raise typer.Exit(code=1)

        rows = []
        for n in notes:
            nstatus = getattr(n, "status", None) or ""
            if status != "all" and nstatus != status:
                continue
            conf = getattr(n, "confidence", None) or 0.0
            if conf < min_confidence:
                continue
            rows.append(
                {
                    "id": n.id,
                    "title": n.title,
                    "confidence": conf,
                    "knowledge_type": getattr(n, "knowledge_type", "") or "",
                    "status": nstatus,
                    "gem_level": getattr(n, "gem_level", "") or "",
                }
            )
            if len(rows) >= limit:
                break

        if output_format == "json":
            # 用 typer.echo 直接输出，避免 Rich console 对 \n 二次转义（破坏 JSON）
            typer.echo(
                _json.dumps({"candidates": rows, "total": len(rows)}, ensure_ascii=False, indent=2)
            )
            return

        table = Table(title=f"候选宝石（共 {len(rows)} 条）")
        for col in ("ID", "标题", "置信度", "类型", "状态", "等级"):
            table.add_column(col)
        for r in rows:
            table.add_row(
                r["id"],
                r["title"],
                f"{r['confidence']:.2f}",
                r["knowledge_type"],
                r["status"],
                r["gem_level"],
            )
        console.print(table)


@candidates_app.command("promote")
def promote_cmd(
    note_id: str = typer.Argument(..., help="candidate 笔记 ID"),
    kb: Optional[str] = typer.Option(None, "--kb", "-k", help="目标知识库名称"),
    output_format: str = typer.Option("table", "--format", "-f", help="table, json"),
) -> None:
    """晋升 candidate → permanent（改 type + 移文件 + 回填 backlinks）"""
    from ..config import use_kb
    from ..note import promote_note

    with use_kb(kb):
        try:
            ok = promote_note(note_id)
        except Exception as e:
            # 索引损坏/IO 等异常：结构化错误（AGENTS.md 约定），不崩 traceback
            if output_format == "json":
                typer.echo(
                    _json.dumps(
                        {"promoted": note_id, "success": False, "error": str(e)},
                        ensure_ascii=False,
                    )
                )
            else:
                console.print(f"[red]✗ 晋升异常：{e}[/red]")
            raise typer.Exit(code=1)
        if output_format == "json":
            typer.echo(_json.dumps({"promoted": note_id, "success": ok}, ensure_ascii=False))
        elif ok:
            console.print(f"[green]✓[/green] 晋升 {note_id} → permanent")
        else:
            console.print(f"[red]✗ 晋升失败：{note_id}（非 candidate 或不存在）[/red]")
        if not ok:
            raise typer.Exit(code=1)


@candidates_app.command("reject")
def reject_cmd(
    note_id: str = typer.Argument(..., help="candidate 笔记 ID"),
    reason: Optional[str] = typer.Option(
        None, "--reason", "-r", help="拒绝原因（记入 frontmatter）"
    ),
    kb: Optional[str] = typer.Option(None, "--kb", "-k", help="目标知识库名称"),
    output_format: str = typer.Option("table", "--format", "-f", help="table, json"),
) -> None:
    """拒绝 candidate（归档丢弃，可记原因，可 jfox unarchive 恢复）"""
    from ..config import use_kb
    from ..note import reject_note

    with use_kb(kb):
        try:
            ok = reject_note(note_id, reason=reason)
        except Exception as e:
            if output_format == "json":
                typer.echo(
                    _json.dumps(
                        {"rejected": note_id, "success": False, "error": str(e)},
                        ensure_ascii=False,
                    )
                )
            else:
                console.print(f"[red]✗ 拒绝异常：{e}[/red]")
            raise typer.Exit(code=1)
        if output_format == "json":
            typer.echo(_json.dumps({"rejected": note_id, "success": ok}, ensure_ascii=False))
        elif ok:
            console.print(f"[green]✓[/green] 拒绝 {note_id}（已归档）")
        else:
            console.print(f"[red]✗ 拒绝失败：{note_id} 不存在[/red]")
        if not ok:
            raise typer.Exit(code=1)


__all__ = ["candidates_app", "gem_synth_app"]


# ---------------------------------------------------------------------------
# gem-synth status 子命令组：合成进度（pending/success/failed）+ 失败复核
# ---------------------------------------------------------------------------

gem_synth_app = typer.Typer(
    name="gem-synth",
    help="L3 宝石合成进度查看（pending/success/failed + 失败复核）",
    no_args_is_help=True,
)


# 强制走子命令分发：单命令 Typer app 默认会被压平（直接当成单命令调用），
# 导致 `gem-synth status` 把 status 当成命令的额外参数。空 callback 让 Typer
# 始终在命令名这一层先解析，子命令（status 等）才能被识别。
@gem_synth_app.callback()
def _gem_synth_callback() -> None:
    """L3 宝石合成进度查看（子命令分发入口）。"""
    return None


@gem_synth_app.command("status")
def gem_synth_status(
    failed_only: bool = typer.Option(False, "--failed", help="只列失败锚点（人工复核）"),
    output_format: str = typer.Option("table", "--format", "-f", help="table, json"),
) -> None:
    """查看合成进度：待处理/成功/失败/重复跳过；--failed 列失败锚点"""
    import json as _json_module

    from ..fragment.store import default_db_path
    from ..global_config import get_global_config_manager
    from .anchors import count_anchors
    from .store import SynthesisLog

    log = None  # 先声明，finally 安全引用（SynthesisLog 构造失败时仍要 close 守卫）
    try:
        cfg = get_global_config_manager().get_gem_synthesis_config()
        log = SynthesisLog()
        counts = log.status_counts()
        success = counts.get("success", 0)
        failed = counts.get("failed", 0)
        duplicate = counts.get("duplicate", 0)
        total = count_anchors(default_db_path(), anchor_types=cfg.anchor_types)
        # duplicate 也算"已处理"（锚点不重试），从 pending 里扣除
        pending = max(0, total - success - failed - duplicate)

        if failed_only:
            failed_list = log.list_failed()
            if output_format == "json":
                typer.echo(
                    _json_module.dumps({"failed": failed_list}, ensure_ascii=False, indent=2)
                )
            else:
                t = Table(title=f"失败锚点（共 {len(failed_list)} 条，人工复核）")
                for c in ("碎片ID", "失败原因", "时间"):
                    t.add_column(c)
                for f in failed_list:
                    t.add_row(
                        str(f["anchor_fragment_id"]),
                        f["fail_reason"] or "",
                        str(f["synthesized_at"]),
                    )
                console.print(t)
            return

        if output_format == "json":
            typer.echo(
                _json_module.dumps(
                    {
                        "pending": pending,
                        "success": success,
                        "failed": failed,
                        "duplicate": duplicate,
                        "total": total,
                    },
                    ensure_ascii=False,
                    indent=2,
                )
            )
        else:
            console.print("[bold]合成进度[/bold]")
            console.print(f"  待处理（pending）:  {pending}")
            console.print(f"  成功（success）:    {success}")
            console.print(f"  失败（failed）:     {failed}")
            console.print(f"  重复跳过（duplicate）：[bold]{duplicate}[/bold]")
            if failed:
                console.print("[dim]用 `jfox gem-synth status --failed` 查看失败锚点[/dim]")
    except Exception as e:
        # 错误响应用 ok（bool），与正常响应里的 success（int 计数）区分，避免语义冲突
        if output_format == "json":
            typer.echo(_json_module.dumps({"ok": False, "error": str(e)}, ensure_ascii=False))
        else:
            console.print(f"[red]读取合成进度失败：{e}[/red]")
        raise typer.Exit(code=1)
    finally:
        # log 可能为 None（构造时抛异常 → 上面 log = SynthesisLog() 未赋值成功）
        if log is not None:
            log.close()


def _dedup_backfill_impl(kb: Optional[str]) -> tuple[int, int]:
    """扫 kb 的 candidate(非 archived)+permanent，灌 dedup 表。返回 (n_cand, n_perm)。

    幂等可重跑：upsert_dedup 内部按 content_hash 命中跳过省 daemon 调用。
    NoteMeta 不含正文，需 load_note_by_id 取 .content。"""
    from ..config import use_kb
    from ..models import NoteType
    from ..note import load_note_by_id
    from ..note_index import get_note_index
    from .dedup import upsert_dedup

    n_cand = n_perm = 0
    with use_kb(kb):
        idx = get_note_index()
        for meta in idx.get_all_meta():
            if meta.archived:
                continue
            if meta.type == NoteType.CANDIDATE:
                note = load_note_by_id(meta.id)
                upsert_dedup(kb, meta.id, "candidate", note.content if note else "")
                n_cand += 1
            elif meta.type == NoteType.PERMANENT:
                note = load_note_by_id(meta.id)
                upsert_dedup(kb, meta.id, "permanent", note.content if note else "")
                n_perm += 1
    return n_cand, n_perm


@gem_synth_app.command("dedup-backfill")
def dedup_backfill_cmd(
    kb: Optional[str] = typer.Option(None, "--kb", "-k", help="目标知识库名称"),
) -> None:
    """一次性把 candidate(非 archived)+permanent 的正文 embedding 灌入 dedup 库。

    幂等可重跑；content_hash 命中则跳过省 daemon 调用。首次启用 dedup 或补灌
    历史笔记后执行，让后续合成周期 dedup_check 能查到已有笔记。"""
    from ..global_config import get_global_config_manager

    target_kb = kb or get_global_config_manager().get_gem_synthesis_config().target_kb
    n_cand, n_perm = _dedup_backfill_impl(target_kb)
    typer.echo(f"已灌入 {n_cand + n_perm} 条（candidate {n_cand} / permanent {n_perm}）到 dedup 库")
