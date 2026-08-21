"""Fast tests for the MOC density diagnostic command."""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest
from typer.testing import CliRunner

from jfox.cli import app
from jfox.moc.cli import moc_app
from jfox.moc.cluster import (
    ClusterMember,
    ClusterSummary,
    CoverageReport,
    MocDiagnoseError,
    MocDiagnoseReport,
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
        orphans=OrphanSummary(count=2, notes=[member]),
        warnings=["diagnostic warning"],
    )


def test_moc_registered_on_root_app():
    result = root_runner.invoke(app, ["moc", "--help"])
    assert result.exit_code == 0
    assert "diagnose" in result.output


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
    assert "must be one of" in result.output


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
    assert message in result.output


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
    assert message in result.output


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
        assert "run index rebuild first" in result.output
