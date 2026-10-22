"""CLI for the similarity baseline and S2 dedup judgment."""

from __future__ import annotations

import json
from pathlib import Path
from typing import NoReturn, Optional

import typer
from rich.console import Console
from rich.table import Table

from .config import ZKConfig, config, use_kb

similarity_app = typer.Typer(
    name="similarity",
    help="查看相似度基线并判定候选笔记",
    no_args_is_help=True,
)

_json_console = Console(legacy_windows=False, highlight=False, markup=False, no_color=True)
_console = Console(legacy_windows=False, no_color=True, highlight=False)


def _current_config() -> ZKConfig:
    return ZKConfig.for_kb(config.base_dir)


def _fail(message: str, output_format: str) -> NoReturn:
    if output_format == "json":
        _json_console.print(
            json.dumps({"success": False, "error": message}, ensure_ascii=False),
            soft_wrap=True,
        )
    else:
        _console.print(f"Error: {message}")
    raise typer.Exit(1)


@similarity_app.command("stats", help="显示永久笔记的最近邻相似度分布。")
def stats_cmd(
    kb: Optional[str] = typer.Option(None, "--kb", "-k"),
    refresh: bool = typer.Option(False, "--refresh"),
    output_format: str = typer.Option("table", "--format", "-f"),
    json_output: bool = typer.Option(False, "--json"),
) -> None:
    """显示当前知识库的相似度基线。"""
    if json_output:
        output_format = "json"
    if output_format not in {"table", "json"}:
        _fail("format must be table or json", output_format)

    try:
        with use_kb(kb):
            cfg = _current_config()
            from .similarity import (
                MIN_BASELINE_NOTES,
                baseline_public_dict,
                compute_baseline,
                current_model_name,
                load_live_records,
            )

            records = load_live_records(cfg)
            baseline = compute_baseline(cfg, refresh=refresh, records=records)
            payload = {
                "success": True,
                "kb": cfg.base_dir.name,
                "model": current_model_name(cfg),
                "dimension": int(records.matrix.shape[1]) if records.matrix.size else 0,
                "note_count": len(records.ids),
                "sampled": baseline.sampled if baseline is not None else False,
                "baseline": baseline_public_dict(baseline) if baseline is not None else None,
                "policy": {"pass_below": 50, "gray_below": 90},
                "cached": baseline.from_cache if baseline is not None else False,
                "computed_at": baseline.computed_at if baseline is not None else None,
                "unavailable_reason": (
                    None
                    if baseline is not None
                    else f"baseline needs at least {MIN_BASELINE_NOTES} permanent notes"
                ),
            }
    except Exception as exc:
        _fail(str(exc), output_format)

    if output_format == "json":
        _json_console.print(json.dumps(payload, ensure_ascii=False, indent=2), soft_wrap=True)
        return

    _console.print(
        f"KB: {payload['kb']}  model: {payload['model']}  "
        f"dim: {payload['dimension']}  notes: {payload['note_count']}"
    )
    if payload["baseline"] is None:
        _console.print(f"Unavailable: {payload['unavailable_reason']}")
        return
    table = Table(show_header=True, box=None)
    table.add_column("quantile")
    table.add_column("score")
    for key in ("p50", "p75", "p90", "p95", "p99"):
        table.add_row(key, f"{payload['baseline'][key]:.3f}")
    _console.print(table)


@similarity_app.command("check", help="把候选笔记与库比较并给出分位判定。")
def check_cmd(
    content_file: Optional[Path] = typer.Option(None, "--content-file"),
    content: Optional[str] = typer.Option(None, "--content"),
    title: Optional[str] = typer.Option(None, "--title"),
    exclude_id: Optional[str] = typer.Option(None, "--exclude-id"),
    top: int = typer.Option(3, "--top"),
    pass_below: int = typer.Option(50, "--pass-below"),
    gray_below: int = typer.Option(90, "--gray-below"),
    kb: Optional[str] = typer.Option(None, "--kb", "-k"),
    refresh: bool = typer.Option(False, "--refresh"),
    output_format: str = typer.Option("table", "--format", "-f"),
    json_output: bool = typer.Option(False, "--json"),
) -> None:
    """比较候选笔记与库内永久笔记。"""
    if json_output:
        output_format = "json"
    if output_format not in {"table", "json"}:
        _fail("format must be table or json", output_format)
    if (content_file is None) == (content is None):
        _fail("exactly one of --content-file / --content is required", output_format)
    if not 0 <= pass_below < gray_below <= 100:
        _fail("require 0 <= pass-below < gray-below <= 100", output_format)

    if content_file is not None:
        try:
            text = content_file.read_text(encoding="utf-8")
        except (OSError, UnicodeError) as exc:
            _fail(f"cannot read content file: {exc}", output_format)
    else:
        text = content or ""

    try:
        with use_kb(kb):
            cfg = _current_config()
            from .similarity import check_candidate

            payload = check_candidate(
                cfg,
                title or "",
                text,
                exclude_id=exclude_id,
                top=top,
                pass_below=pass_below,
                gray_below=gray_below,
                refresh=refresh,
            )
    except Exception as exc:
        _fail(str(exc), output_format)

    if output_format == "json":
        _json_console.print(json.dumps(payload, ensure_ascii=False, indent=2), soft_wrap=True)
        return

    _console.print(f"Verdict: {payload['verdict']}")
    if payload.get("unavailable_reason"):
        _console.print(f"Reason: {payload['unavailable_reason']}")
    for match in payload["matches"]:
        _console.print(
            f"- {match['score']:.3f} ({match['percentile']:.1f}%) "
            f"{match['title']} ({match['id']})"
        )
    for warning in payload.get("warnings", []):
        _console.print(f"Warning: {warning}")
