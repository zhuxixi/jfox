"""CLI for diagnosing permanent-note MOC density."""

from __future__ import annotations

import json
import math
from typing import Any, NoReturn, Optional

import typer
from rich.console import Console
from rich.table import Table

from ..config import ZKConfig, config, use_kb
from .cluster import MocDiagnoseError, MocDiagnoseReport, diagnose_moc_density

moc_app = typer.Typer(name="moc", help="诊断和维护 MOC 结构层", no_args_is_help=True)


@moc_app.callback()
def _moc_callback() -> None:
    """MOC command group callback."""


_json_console = Console(
    legacy_windows=False,
    highlight=False,
    markup=False,
    no_color=True,
)
_console = Console(legacy_windows=False, no_color=True)


def _member_to_dict(member: Any) -> dict[str, Any]:
    result = {
        "id": member.id,
        "title": member.title,
        "link_degree": member.link_degree,
        "mean_similarity": member.mean_similarity,
    }
    for flag in ("link_orphan", "semantic_orphan"):
        if hasattr(member, flag):
            result[flag] = bool(getattr(member, flag))
    return result


def report_to_dict(report: MocDiagnoseReport, kb: Optional[str] = None) -> dict[str, Any]:
    """Convert a diagnostic report to the stable JSON response contract."""
    coverage = report.coverage
    suggested = report.suggest
    suggest_data = None
    if suggested is not None:
        suggest_data = {
            "threshold": suggested.threshold,
            "clusters": [
                {
                    "size": cluster.size,
                    "hub": _member_to_dict(cluster.hub) if cluster.hub else None,
                    "members": [_member_to_dict(member) for member in cluster.members],
                }
                for cluster in suggested.clusters
            ],
        }

    return {
        "success": True,
        "kb": kb if kb is not None else config.base_dir.name,
        "coverage": {
            "filesystem": coverage.filesystem,
            "vector": coverage.vector,
            "vector_orphans": coverage.vector_orphans,
            "bm25": coverage.bm25,
            "bm25_coverage_ratio": coverage.bm25_coverage_ratio,
            "warnings": list(coverage.warnings),
        },
        "threshold_sweep": [
            {
                "threshold": summary.threshold,
                "cluster_count": summary.cluster_count,
                "max_cluster_size": summary.max_cluster_size,
                "orphan_count": summary.orphan_count,
            }
            for summary in report.threshold_sweep
        ],
        "suggest": suggest_data,
        "orphans": {
            "count": report.orphans.count,
            "notes": [_member_to_dict(note) for note in report.orphans.notes],
        },
        "warnings": list(report.warnings),
    }


def _parse_thresholds(raw: str) -> list[float]:
    values = raw.split(",")
    thresholds: list[float] = []
    for value in values:
        stripped = value.strip()
        if not stripped:
            raise ValueError("threshold values must not be empty")
        try:
            threshold = float(stripped)
        except ValueError as exc:
            raise ValueError(f"invalid threshold: {stripped}") from exc
        if not 0 < threshold < 1:
            raise ValueError("thresholds must be strictly between 0 and 1")
        if threshold in thresholds:
            raise ValueError(f"duplicate threshold: {stripped}")
        thresholds.append(threshold)
    return thresholds


def _fail(message: str, output_format: str) -> NoReturn:
    if output_format == "json":
        _json_console.print(
            json.dumps({"success": False, "error": message}, ensure_ascii=False),
            soft_wrap=True,
        )
    else:
        _console.print(message)
    raise typer.Exit(code=1)


def _render_table(report: MocDiagnoseReport, top: int) -> None:
    """Render the report as four readable sections."""
    _console.print("Permanent coverage")
    coverage_table = Table(show_header=True, box=None)
    coverage_table.add_column("filesystem")
    coverage_table.add_column("vector")
    coverage_table.add_column("bm25")
    coverage_table.add_row(
        str(report.coverage.filesystem) if report.coverage.filesystem is not None else "N/A",
        str(report.coverage.vector) if report.coverage.vector is not None else "N/A",
        str(report.coverage.bm25) if report.coverage.bm25 is not None else "N/A",
    )
    _console.print(coverage_table)
    for warning in report.coverage.warnings:
        _console.print(f"Warning: {warning}")

    _console.print("Threshold sensitivity")
    threshold_table = Table(show_header=True, box=None)
    for column in ("threshold", "cluster_count", "max_cluster_size", "orphan_count"):
        threshold_table.add_column(column)
    for summary in report.threshold_sweep:
        threshold_table.add_row(
            str(summary.threshold),
            str(summary.cluster_count),
            str(summary.max_cluster_size),
            str(summary.orphan_count),
        )
    _console.print(threshold_table)

    threshold = report.suggest.threshold if report.suggest is not None else "N/A"
    _console.print(f"Suggested MOC clusters (threshold={threshold}, top={top})")
    if report.suggest is None or not report.suggest.clusters:
        _console.print("(none)")
    else:
        for index, cluster in enumerate(report.suggest.clusters, start=1):
            hub = cluster.hub
            hub_text = f"{hub.title} ({hub.link_degree})" if hub else "(none)"
            members = ", ".join(member.title for member in cluster.members[:5])
            _console.print(f"{index}. {cluster.size} members; hub: {hub_text}; members: {members}")

    _console.print("Permanent orphans")
    _console.print(f"{report.orphans.count} note(s)")
    for note in report.orphans.notes[:10]:
        _console.print(f"- {note.title} ({note.id})")
    for warning in report.warnings:
        if warning not in report.coverage.warnings:
            _console.print(f"Warning: {warning}")


@moc_app.command("diagnose")
def diagnose_cmd(
    thresholds: str = typer.Option("0.55,0.6,0.65,0.7", "--thresholds"),
    min_size: int = typer.Option(3, "--min-size"),
    suggest_threshold: float = typer.Option(0.65, "--suggest-threshold"),
    top: int = typer.Option(10, "--top"),
    kb: Optional[str] = typer.Option(None, "--kb", "-k"),
    output_format: str = typer.Option("table", "--format", "-f"),
    json_output: bool = typer.Option(False, "--json"),
) -> None:
    """诊断永久笔记的语义密度和 MOC 聚类建议。"""
    if json_output:
        output_format = "json"
    if output_format not in {"table", "json"}:
        _fail("format must be table or json", output_format)
    try:
        parsed_thresholds = _parse_thresholds(thresholds)
        if min_size < 2:
            raise ValueError("min_size must be at least 2")
        if top < 1:
            raise ValueError("top must be at least 1")
        if not any(
            math.isclose(suggest_threshold, threshold, abs_tol=1e-9, rel_tol=0)
            for threshold in parsed_thresholds
        ):
            raise ValueError("suggest threshold must be one of the supplied thresholds")
    except ValueError as exc:
        _fail(str(exc), output_format)

    try:
        with use_kb(kb):
            active_config = ZKConfig.for_kb(config.base_dir)
            report = diagnose_moc_density(
                active_config,
                thresholds=parsed_thresholds,
                min_size=min_size,
                suggest_threshold=suggest_threshold,
                top=top,
            )
            payload = report_to_dict(report, kb=kb)
    except (MocDiagnoseError, ValueError, OSError) as exc:
        _fail(str(exc), output_format)

    if output_format == "json":
        _json_console.print(json.dumps(payload, ensure_ascii=False, indent=2), soft_wrap=True)
    else:
        _render_table(report, top)
