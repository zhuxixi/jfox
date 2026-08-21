"""永久笔记 MOC 密度诊断命令。"""

from __future__ import annotations

import json
import math
from typing import TYPE_CHECKING, Any, NoReturn, Optional

import typer
from rich.console import Console
from rich.table import Table

from ..config import ZKConfig, config, use_kb
from ..models import Note, NoteType
from ..note_index import get_note_index
from . import MocDiagnoseError

if TYPE_CHECKING:
    from .cluster import MocDiagnoseReport


def diagnose_moc_density(*args: Any, **kwargs: Any) -> Any:
    """按需加载聚类服务，避免根命令启动时引入重依赖。"""
    from .cluster import diagnose_moc_density as diagnose

    return diagnose(*args, **kwargs)


def write_moc(*args: Any, **kwargs: Any) -> Any:
    """按需加载写盘逻辑，避免根命令启动时引入重依赖。"""
    from .generate import write_moc as _write_moc

    return _write_moc(*args, **kwargs)


def list_notes(*args: Any, **kwargs: Any) -> Any:
    """按需加载 note.list_notes，避免根命令启动时引入重依赖。"""
    from ..note import list_notes as _list_notes

    return _list_notes(*args, **kwargs)


def load_note_by_id(*args: Any, **kwargs: Any) -> Any:
    """按需加载 note.load_note_by_id。"""
    from ..note import load_note_by_id as _load

    return _load(*args, **kwargs)


def update_note(*args: Any, **kwargs: Any) -> Any:
    """按需加载 note.update_note。"""
    from ..note import update_note as _update_note

    return _update_note(*args, **kwargs)


def backfill_moc_backlinks(*args: Any, **kwargs: Any) -> Any:
    """按需加载 generate.backfill_moc_backlinks。"""
    from .generate import backfill_moc_backlinks as _backfill

    return _backfill(*args, **kwargs)


def remove_moc_backlinks(*args: Any, **kwargs: Any) -> Any:
    """按需加载 generate.remove_moc_backlinks。"""
    from .generate import remove_moc_backlinks as _remove

    return _remove(*args, **kwargs)


moc_app = typer.Typer(name="moc", help="诊断和维护 MOC 结构层", no_args_is_help=True)


@moc_app.callback()
def _moc_callback() -> None:
    """MOC 命令组回调。"""


_json_console = Console(
    legacy_windows=False,
    highlight=False,
    markup=False,
    no_color=True,
)
_console = Console(legacy_windows=False, no_color=True, highlight=False)


def _member_to_dict(member: Any) -> dict[str, Any]:
    """将聚类成员转换为稳定的 JSON 字段。"""
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


def report_to_dict(report: "MocDiagnoseReport", kb: Optional[str] = None) -> dict[str, Any]:
    """将诊断报告转换为稳定的 JSON 响应契约。"""
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
    """解析并校验逗号分隔的相似度阈值。"""
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
    """按请求格式输出错误并以状态码 1 退出。"""
    if output_format == "json":
        _json_console.print(
            json.dumps({"success": False, "error": message}, ensure_ascii=False),
            soft_wrap=True,
        )
    else:
        _console.print(message)
    raise typer.Exit(code=1)


def _render_table(report: MocDiagnoseReport, top: int) -> None:
    """将报告渲染为四个易读区段。"""
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


def draft_to_dict(
    threshold: float,
    cluster: Any,
    draft: Any,
    created: Optional[dict] = None,
    warnings: Optional[list[str]] = None,
) -> dict[str, Any]:
    """把创建结果转成稳定的 JSON 契约。"""
    return {
        "success": True,
        "threshold": threshold,
        "cluster": {
            "size": cluster.size,
            "hub": _member_to_dict(cluster.hub) if cluster.hub else None,
        },
        "draft": {
            "title": draft.title,
            "groups": [
                {"name": group.name, "members": [_member_to_dict(m) for m in group.members]}
                for group in draft.groups
            ],
            "orphan_bucket": [_member_to_dict(o) for o in draft.orphan_bucket],
            "total_members": draft.total_members,
        },
        "created": created,
        "warnings": list(warnings or []),
    }


def _render_draft(draft: Any, cluster: Any) -> None:
    """table 格式的草稿预览。"""
    hub_title = cluster.hub.title if cluster and cluster.hub else "N/A"
    _console.print(f"Cluster size {cluster.size}; hub: {hub_title}")
    _console.print(f"MOC title: {draft.title}")
    for group in draft.groups:
        _console.print(f"## {group.name} ({len(group.members)})")
        for member in group.members:
            _console.print(f"- [[{member.title}]] — {member.link_degree} links")
    if draft.orphan_bucket:
        _console.print(f"## 待归类 ({len(draft.orphan_bucket)})")
        for orphan in draft.orphan_bucket:
            _console.print(f"- [[{orphan.title}]] — {orphan.link_degree} links")


def _create_impl(
    active_config: ZKConfig,
    threshold: float,
    cluster_index: int,
    max_size: int,
    title: Optional[str],
    include_orphans: bool,
    write: bool,
) -> tuple[dict[str, Any], Optional[Note], Any, Any]:
    """create 核心逻辑：诊断 → 选簇 → 草稿 → 可选落盘。

    返回 (payload, moc, draft, cluster) 四元组，供 create_cmd 渲染 table 或 JSON。
    """
    # 延迟导入：draft.py → cluster.py → networkx/numpy，不能在模块顶层加载
    from .draft import build_moc_draft, filter_live_members

    report = diagnose_moc_density(
        active_config,
        thresholds=[threshold],
        min_size=2,
        suggest_threshold=threshold,
        top=cluster_index + 1,
    )
    suggest = report.suggest
    if suggest is None or cluster_index >= len(suggest.clusters):
        raise MocDiagnoseError(
            f"No cluster at index {cluster_index}; run `jfox moc diagnose` to see clusters"
        )
    cluster = suggest.clusters[cluster_index]
    note_index = get_note_index(active_config)
    all_meta = note_index.get_all_meta()
    tags_by_id = {meta.id: list(meta.tags) for meta in all_meta}
    # live permanent ids：用于落盘前过滤 ghost 成员（spec D6）
    live_ids = {
        meta.id for meta in all_meta if meta.type == NoteType.PERMANENT and not meta.archived
    }
    orphans = report.orphans.notes if include_orphans else None
    draft = build_moc_draft(cluster, tags_by_id, max_size, orphans=orphans, title=title)
    # 落盘前过滤 ghost 成员（spec D6：已归档/不存在的成员跳过并计入 warning）
    draft, ghost_warnings = filter_live_members(draft, live_ids)
    created: Optional[dict[str, str]] = None
    moc: Optional[Note] = None
    if write:
        moc = write_moc(draft)
        created = {"id": moc.id, "filepath": str(moc.filepath)}
    payload = draft_to_dict(threshold, cluster, draft, created, warnings=ghost_warnings)
    return payload, moc, draft, cluster


@moc_app.command(
    "create",
    help="从诊断主题簇生成 MOC 笔记草稿（dry-run 默认，--yes 落盘）。",
)
def create_cmd(
    threshold: float = typer.Option(0.65, "--threshold"),
    cluster_index: int = typer.Option(0, "--cluster"),
    max_size: int = typer.Option(50, "--max-size"),
    title: Optional[str] = typer.Option(None, "--title"),
    include_orphans: bool = typer.Option(False, "--include-orphans"),
    yes: bool = typer.Option(False, "--yes"),
    kb: Optional[str] = typer.Option(None, "--kb", "-k"),
    output_format: str = typer.Option("table", "--format", "-f"),
) -> None:
    """从诊断主题簇生成 MOC 笔记草稿。"""
    if output_format not in {"table", "json"}:
        _fail("format must be table or json", output_format)
    if not 0 < threshold < 1:
        _fail("threshold must be strictly between 0 and 1", output_format)
    if cluster_index < 0:
        _fail("cluster index must be >= 0", output_format)
    if max_size < 1:
        _fail("max_size must be at least 1", output_format)

    try:
        with use_kb(kb):
            active_config = ZKConfig.for_kb(config.base_dir)
            payload, moc, draft, cluster = _create_impl(
                active_config, threshold, cluster_index, max_size, title, include_orphans, yes
            )
    except (MocDiagnoseError, ValueError, OSError) as exc:
        _fail(str(exc), output_format)

    if output_format == "json":
        _json_console.print(json.dumps(payload, ensure_ascii=False, indent=2), soft_wrap=True)
    else:
        _render_draft(draft, cluster)
        if moc is not None:
            _console.print(f"Created MOC {moc.id} at {moc.filepath}")


def _update_impl(
    active_config: ZKConfig,
    moc_id: Optional[str],
    threshold: float,
    apply: bool,
) -> tuple[list[dict[str, Any]], list[Note]]:
    """update 核心逻辑：诊断一次 → 每个 structure 笔记匹配簇 → diff → 可选应用。

    返回 (payloads, changed)：payloads 是每个 MOC 的 diff；changed 是实际更新的 Note 列表。
    """
    # 延迟导入：draft.py → cluster.py → networkx/numpy，不能在模块顶层加载
    from .draft import build_update_diff

    if moc_id is not None:
        moc = load_note_by_id(moc_id)
        if moc is None:
            raise MocDiagnoseError(f"MOC note not found: {moc_id}")
        if moc.type != NoteType.STRUCTURE:
            raise MocDiagnoseError(f"Note {moc_id} is not a structure note (type={moc.type.value})")
        moc_notes = [moc]
    else:
        moc_notes = list_notes(note_type=NoteType.STRUCTURE, cfg=active_config)
    if not moc_notes:
        raise MocDiagnoseError("No structure notes found; run `jfox moc create` first")

    report = diagnose_moc_density(
        active_config,
        thresholds=[threshold],
        min_size=2,
        suggest_threshold=threshold,
        top=100,
    )
    clusters = report.suggest.clusters if report.suggest is not None else []

    note_index = get_note_index(active_config)
    # live_note_ids 覆盖任意笔记类型（不限 permanent）：
    # 死链判定按「已归档/不存在」，live 但非 permanent 的链接不摘除（spec D7）
    live_note_ids = {meta.id for meta in note_index.get_all_meta() if not meta.archived}

    payloads: list[dict[str, Any]] = []
    changed: list[Note] = []
    for moc in moc_notes:
        current = set(moc.links)
        # 匹配：与 links 交集最大的簇
        best: Optional[Any] = None
        best_overlap = -1
        for cluster in clusters:
            overlap = len(current & {m.id for m in cluster.members})
            if overlap > best_overlap:
                best_overlap = overlap
                best = cluster
        if best is None or best_overlap == 0:
            payloads.append(
                {
                    "moc_id": moc.id,
                    "moc_title": moc.title,
                    "add": [],
                    "remove": [],
                    "kept": 0,
                    "warning": "no matching cluster; skipped",
                }
            )
            continue

        diff = build_update_diff(moc.links, best.members, live_note_ids)
        payload: dict[str, Any] = {
            "moc_id": moc.id,
            "moc_title": moc.title,
            "add": [_member_to_dict(m) for m in diff.add],
            "remove": list(diff.remove),
            "kept": diff.kept,
        }

        if apply and (diff.add or diff.remove):
            add_ids = [m.id for m in diff.add]
            moc.links = sorted(set(moc.links + add_ids) - set(diff.remove))
            # 检查 update_note 返回值：写盘失败时不回填/摘除 backlinks（与 write_moc 对齐，#413 CR issue-1）
            if not update_note(moc):
                payload["warning"] = "update failed; backlinks untouched"
                payloads.append(payload)
                continue
            backfill_moc_backlinks(moc, add_ids)
            remove_moc_backlinks(moc.id, diff.remove)
            changed.append(moc)
        payloads.append(payload)

    return payloads, changed


@moc_app.command(
    "update",
    help="重扫主题簇，diff 现有 MOC 成员（增补新笔记、摘除死链）。",
)
def update_cmd(
    moc_id: Optional[str] = typer.Option(None, "--id", help="MOC 笔记 id（缺省=全部 structure）"),
    threshold: float = typer.Option(0.65, "--threshold"),
    yes: bool = typer.Option(False, "--yes"),
    kb: Optional[str] = typer.Option(None, "--kb", "-k"),
    output_format: str = typer.Option("table", "--format", "-f"),
) -> None:
    """重扫主题簇，diff 现有 MOC 成员。"""
    if output_format not in {"table", "json"}:
        _fail("format must be table or json", output_format)
    if not 0 < threshold < 1:
        _fail("threshold must be strictly between 0 and 1", output_format)

    try:
        with use_kb(kb):
            active_config = ZKConfig.for_kb(config.base_dir)
            payloads, changed = _update_impl(active_config, moc_id, threshold, yes)
    except (MocDiagnoseError, ValueError, OSError) as exc:
        _fail(str(exc), output_format)

    wrapper = {"success": True, "updates": payloads, "applied": len(changed) > 0}
    if output_format == "json":
        _json_console.print(json.dumps(wrapper, ensure_ascii=False, indent=2), soft_wrap=True)
    else:
        for payload in payloads:
            _console.print(f"[{payload['moc_id']}] {payload['moc_title']}")
            for member in payload["add"]:
                _console.print(f"  + [[{member['title']}]] ({member['id']})")
            for rid in payload["remove"]:
                _console.print(f"  - {rid} (dead link)")
            if not payload["add"] and not payload["remove"]:
                _console.print("  (no changes)")
            if payload.get("warning"):
                _console.print(f"  Warning: {payload['warning']}")


@moc_app.command(
    "diagnose",
    help="诊断永久笔记的语义密度和 MOC 聚类建议。",
)
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
