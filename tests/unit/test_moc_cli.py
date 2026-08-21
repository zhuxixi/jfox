"""MOC 密度诊断命令的快速测试。"""

from __future__ import annotations

import json
import re
import subprocess
import sys
from unittest.mock import MagicMock, patch

import pytest
from typer.testing import CliRunner

from jfox import __version__
from jfox.cli import app
from jfox.moc.cli import moc_app, report_to_dict
from jfox.moc.cluster import (
    ClusterMember,
    ClusterSummary,
    CoverageReport,
    MocDiagnoseError,
    MocDiagnoseReport,
    OrphanNote,
    OrphanSummary,
    SuggestedReport,
    ThresholdSummary,
)

runner = CliRunner()
root_runner = CliRunner()


def _report() -> MocDiagnoseReport:
    member = ClusterMember(id="1", title="Alpha", link_degree=2, mean_similarity=0.9)
    return MocDiagnoseReport(
        coverage=CoverageReport(
            filesystem=5,
            vector=7,
            vector_orphans=2,
            bm25=4,
            bm25_coverage_ratio=0.8,
            warnings=["Vector index contains 2 permanent orphan(s)"],
        ),
        threshold_sweep=[
            ThresholdSummary(0.55, 1, 3, 2),
            ThresholdSummary(0.6, 1, 3, 2),
            ThresholdSummary(0.65, 1, 3, 2),
            ThresholdSummary(0.7, 0, 0, 5),
        ],
        suggest=SuggestedReport(
            threshold=0.65,
            clusters=[ClusterSummary(size=1, members=[member], hub=member)],
        ),
        orphans=OrphanSummary(count=2, notes=[OrphanNote("1", "Alpha", True, True)]),
        warnings=["diagnostic warning"],
    )


_ANSI_RE = re.compile(r"\x1b\[[0-9;]*m")


def _strip_ansi(text: str) -> str:
    """移除 rich/typer 在彩色终端下输出的 ANSI 转义码（如 CI 的 PY_COLORS=1）。"""
    return _ANSI_RE.sub("", text)


def _help_lines(output: str) -> list[str]:
    return [" ".join(_strip_ansi(line).split()) for line in output.splitlines() if line.strip()]


def test_root_help_registers_exact_moc_contract():
    result = root_runner.invoke(app, ["--help"])

    assert result.exit_code == 0
    assert "│ moc 诊断和维护 MOC 结构层 │" in _help_lines(result.output)


def test_moc_help_registers_exact_diagnose_contract():
    result = root_runner.invoke(app, ["moc", "--help"])

    assert result.exit_code == 0
    assert "Usage: jfox moc [OPTIONS] COMMAND [ARGS]..." in _help_lines(result.output)
    assert "│ diagnose 诊断永久笔记的语义密度和 MOC 聚类建议。 │" in _help_lines(result.output)


def test_moc_diagnose_help_preserves_exact_baseline_contract():
    result = root_runner.invoke(app, ["moc", "diagnose", "--help"])

    assert result.exit_code == 0
    lines = _help_lines(result.output)
    assert "Usage: jfox moc diagnose [OPTIONS]" in lines
    assert lines.count("诊断永久笔记的语义密度和 MOC 聚类建议。") == 1


def test_import_root_cli_keeps_moc_registered_without_heavy_dependencies():
    script = """
import json
import sys
import jfox.cli as cli
print(json.dumps({
    "groups": [group.name for group in cli.app.registered_groups],
    "chromadb_loaded": "chromadb" in sys.modules,
    "networkx_loaded": "networkx" in sys.modules,
    "numpy_loaded": "numpy" in sys.modules,
}))
"""

    result = subprocess.run(
        [sys.executable, "-c", script],
        check=True,
        capture_output=True,
        text=True,
    )
    payload = json.loads(result.stdout)

    assert payload["groups"].count("moc") == 1
    assert payload["chromadb_loaded"] is False
    assert payload["networkx_loaded"] is False
    assert payload["numpy_loaded"] is False


def test_root_version_still_works_with_moc_registered():
    result = root_runner.invoke(app, ["--version"])

    assert result.exit_code == 0
    assert result.output == f"jfox {__version__}\n"


def test_diagnose_json_contract():
    with patch("jfox.moc.cli.diagnose_moc_density", return_value=_report()):
        result = runner.invoke(moc_app, ["diagnose", "--json"])
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["success"] is True
    assert payload["coverage"]["vector_orphans"] == 2
    assert payload["suggest"]["threshold"] == 0.65
    assert set(payload) == {
        "success",
        "kb",
        "coverage",
        "threshold_sweep",
        "suggest",
        "orphans",
        "warnings",
    }


def test_suggest_threshold_must_be_in_sweep():
    result = runner.invoke(
        moc_app,
        ["diagnose", "--thresholds", "0.6,0.7", "--suggest-threshold", "0.65"],
    )
    assert result.exit_code == 1
    assert "must be one of" in _strip_ansi(result.output)


def test_diagnose_json_preserves_long_multi_word_error_without_ansi():
    message = (
        "The permanent note vector index is unavailable; rebuild the index before running "
        "MOC density diagnosis for this knowledge base"
    )
    with patch(
        "jfox.moc.cli.diagnose_moc_density",
        side_effect=MocDiagnoseError(message),
    ):
        result = runner.invoke(moc_app, ["diagnose", "--json"])

    assert result.exit_code == 1
    payload = json.loads(result.output)
    assert payload["error"] == message
    assert "\x1b" not in result.output


def test_report_json_includes_orphan_source_flags_and_null_coverage():
    report = _report()
    report.coverage.filesystem = None
    report.coverage.bm25 = None
    report.orphans = OrphanSummary(
        count=3,
        notes=[
            OrphanNote("both", "Both", True, True),
            OrphanNote("link", "Link", True, False),
            OrphanNote("semantic", "Semantic", False, True),
        ],
    )

    payload = report_to_dict(report)

    assert payload["coverage"]["filesystem"] is None
    assert payload["coverage"]["bm25"] is None
    assert payload["orphans"]["notes"] == [
        {
            "id": "both",
            "title": "Both",
            "link_degree": 0,
            "mean_similarity": 0.0,
            "link_orphan": True,
            "semantic_orphan": True,
        },
        {
            "id": "link",
            "title": "Link",
            "link_degree": 0,
            "mean_similarity": 0.0,
            "link_orphan": True,
            "semantic_orphan": False,
        },
        {
            "id": "semantic",
            "title": "Semantic",
            "link_degree": 0,
            "mean_similarity": 0.0,
            "link_orphan": False,
            "semantic_orphan": True,
        },
    ]


def test_diagnose_table_has_four_sections_and_permanent_only_coverage():
    with patch("jfox.moc.cli.diagnose_moc_density", return_value=_report()):
        result = runner.invoke(moc_app, ["diagnose"])

    assert result.exit_code == 0, result.output
    for heading in (
        "Permanent coverage",
        "Threshold sensitivity",
        "Suggested MOC clusters",
        "Permanent orphans",
    ):
        assert result.output.count(heading) == 1
    coverage_output = result.output.split("Permanent coverage", 1)[1].split(
        "Threshold sensitivity", 1
    )[0]
    for note_type in ("candidate", "session", "fleeting"):
        assert note_type not in coverage_output.lower()


@pytest.mark.parametrize(
    "thresholds, message",
    [
        ("0.5,nope", "invalid threshold"),
        ("0.5,,0.7", "must not be empty"),
        ("0.5,0.5", "duplicate"),
        ("0,0.7", "strictly between"),
        ("0.5,1", "strictly between"),
    ],
)
def test_threshold_validation(thresholds, message):
    result = runner.invoke(moc_app, ["diagnose", "--thresholds", thresholds])
    assert result.exit_code == 1
    assert message in _strip_ansi(result.output)


@pytest.mark.parametrize(
    "args, message",
    [
        (["--min-size", "1"], "min_size must be at least 2"),
        (["--top", "0"], "top must be at least 1"),
        (["--format", "yaml"], "format must be table or json"),
    ],
)
def test_option_validation(args, message):
    result = runner.invoke(moc_app, ["diagnose", *args])
    assert result.exit_code == 1
    assert message in _strip_ansi(result.output)


def test_kb_is_propagated_and_active_config_is_used():
    context = MagicMock()
    context.__enter__.return_value = None
    context.__exit__.return_value = False
    with (
        patch("jfox.moc.cli.use_kb", return_value=context) as use_kb,
        patch("jfox.moc.cli.config.base_dir", MagicMock(name="work")),
        patch("jfox.moc.cli.diagnose_moc_density", return_value=_report()) as diagnose,
    ):
        result = runner.invoke(moc_app, ["diagnose", "--kb", "work", "--json"])
    assert result.exit_code == 0, result.output
    use_kb.assert_called_once_with("work")
    diagnose.assert_called_once()
    assert json.loads(result.output)["kb"] == "work"


@pytest.mark.parametrize("output_args", [[], ["--json"]])
def test_moc_diagnose_error_is_reported(output_args):
    with patch(
        "jfox.moc.cli.diagnose_moc_density",
        side_effect=MocDiagnoseError("run index rebuild first"),
    ):
        result = runner.invoke(moc_app, ["diagnose", *output_args])
    assert result.exit_code == 1
    if "--json" in output_args:
        assert json.loads(result.output) == {
            "success": False,
            "error": "run index rebuild first",
        }
    else:
        assert "run index rebuild first" in _strip_ansi(result.output)
