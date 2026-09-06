"""CLI 子命令组：jfox gem-synth status（合成进度查看）。

candidate 命令已迁移到 jfox/candidates/（#399 解耦）。
"""

from __future__ import annotations

import json as _json
from typing import Optional

import typer
from rich.console import Console
from rich.table import Table

console = Console(legacy_windows=False)

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
        merged = counts.get("merged", 0)
        total = count_anchors(default_db_path(), anchor_types=cfg.anchor_types)
        # duplicate / merged 都算"已处理"（锚点不重试），从 pending 里扣除
        pending = max(0, total - success - failed - duplicate - merged)

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
                        "merged": merged,
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
            console.print(f"  合并补入（merged）：  {merged}")
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
    计数仅含实际写入的行（upsert_dedup 返回 True），跳过/失败的不计入。
    NoteMeta 不含正文，需 load_note_by_id 取 .content。"""
    from ..config import use_kb
    from ..models import NoteType
    from ..note import load_note_by_id
    from ..note_index import get_note_index
    from .dedup import _resolve_kb_name, upsert_dedup

    n_cand = n_perm = 0
    with use_kb(kb):
        resolved = _resolve_kb_name(kb)  # kb=None → config.base_dir.name（具体 KB 名）
        idx = get_note_index()
        for meta in idx.get_all_meta():
            if meta.archived:
                continue
            if meta.type == NoteType.CANDIDATE:
                note = load_note_by_id(meta.id)
                if upsert_dedup(resolved, meta.id, "candidate", note.content if note else ""):
                    n_cand += 1
            elif meta.type == NoteType.PERMANENT:
                note = load_note_by_id(meta.id)
                if upsert_dedup(resolved, meta.id, "permanent", note.content if note else ""):
                    n_perm += 1
    return n_cand, n_perm


@gem_synth_app.command("dedup-backfill")
def dedup_backfill_cmd(
    kb: Optional[str] = typer.Option(None, "--kb", "-k", help="目标知识库名称"),
    output_format: str = typer.Option("text", "--format", "-f", help="输出格式: text, json"),
) -> None:
    """一次性把 candidate(非 archived)+permanent 的正文 embedding 灌入 dedup 库。

    幂等可重跑；content_hash 命中则跳过省 daemon 调用。首次启用 dedup 或补灌
    历史笔记后执行，让后续合成周期 dedup_check 能查到已有笔记。"""
    from ..global_config import get_global_config_manager

    target_kb = kb or get_global_config_manager().get_gem_synthesis_config().target_kb
    try:
        n_cand, n_perm = _dedup_backfill_impl(target_kb)
    except Exception as e:
        if output_format == "json":
            typer.echo(
                _json.dumps(
                    {"ok": False, "error": str(e)},
                    ensure_ascii=False,
                )
            )
        else:
            console.print(f"[red]dedup-backfill 失败：{e}[/red]")
        raise typer.Exit(code=1)

    total = n_cand + n_perm
    if output_format == "json":
        typer.echo(
            _json.dumps(
                {"candidate": n_cand, "permanent": n_perm, "total": total},
                ensure_ascii=False,
            )
        )
    else:
        typer.echo(f"已灌入 {total} 条（candidate {n_cand} / permanent {n_perm}）到 dedup 库")
