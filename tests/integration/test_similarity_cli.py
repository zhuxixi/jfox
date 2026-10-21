"""CLI contract tests for `jfox similarity` (deterministic stub, no model)."""

import json
from datetime import datetime

import numpy as np
import pytest
from typer.testing import CliRunner

from jfox.cli import app
from jfox.config import ZKConfig
from jfox.similarity import Baseline, LiveRecords

pytestmark = [pytest.mark.integration, pytest.mark.fast]

runner = CliRunner()


def _cfg(tmp_path):
    cfg = ZKConfig(base_dir=tmp_path)
    cfg.ensure_dirs()
    return cfg


def _records():
    return LiveRecords(
        ids=["n0", "n1", "n2"],
        titles=["T0", "T1", "T2"],
        matrix=np.eye(3, dtype=np.float32),
    )


def _baseline():
    return Baseline(
        model="stub",
        dimension=3,
        note_count=3,
        sampled=False,
        quantiles={"p50": 0.6, "p75": 0.7, "p90": 0.8, "p95": 0.9, "p99": 0.95},
        nn_values=np.array([0.5, 0.6, 0.7, 0.8, 0.9, 0.95], dtype=np.float32),
        index_rebuilt_at=None,
        computed_at=datetime(2026, 10, 21, 0, 0, 0).isoformat(),
    )


class _StubBackend:
    def __init__(self, unit_vector):
        self.unit_vector = np.asarray(unit_vector, dtype=np.float32)

    def encode_single(self, text, *, daemon_only=False):
        return self.unit_vector


def _patch_common(monkeypatch, tmp_path, *, with_baseline=True):
    cfg = _cfg(tmp_path)
    monkeypatch.setattr("jfox.similarity_cli._current_config", lambda: cfg)
    monkeypatch.setattr("jfox.similarity.load_live_records", lambda cfg: _records())
    monkeypatch.setattr(
        "jfox.similarity.compute_baseline",
        lambda cfg, **kwargs: _baseline() if with_baseline else None,
    )
    return cfg


def test_stats_json_contract(monkeypatch, tmp_path):
    _patch_common(monkeypatch, tmp_path)
    result = runner.invoke(app, ["similarity", "stats", "--json"])
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["success"] is True
    assert payload["note_count"] == 3
    assert payload["baseline"]["p99"] == pytest.approx(0.95)
    assert payload["policy"] == {"pass_below": 50, "gray_below": 90}


def test_stats_unavailable_when_baseline_missing(monkeypatch, tmp_path):
    _patch_common(monkeypatch, tmp_path, with_baseline=False)
    result = runner.invoke(app, ["similarity", "stats", "--json"])
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["baseline"] is None
    assert payload["unavailable_reason"]


@pytest.mark.parametrize(
    ("unit_vector", "expected"),
    [
        # Negative second component keeps n0 top-1 while its cosine is 0.4 (p0 -> new).
        ([0.4, -0.916, 0.0], "new"),
        ([0.8, 0.6, 0.0], "gray"),
        ([1.0, 0.0, 0.0], "covered"),
    ],
)
def test_check_json_verdicts(monkeypatch, tmp_path, unit_vector, expected):
    _patch_common(monkeypatch, tmp_path)
    monkeypatch.setattr("jfox.embedding_backend.get_backend", lambda: _StubBackend(unit_vector))
    result = runner.invoke(
        app,
        ["similarity", "check", "--content", "草稿正文", "--title", "草稿标题", "--json"],
    )
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["verdict"] == expected
    assert payload["top1"]["id"] == "n0"


def test_check_requires_exactly_one_content_source(monkeypatch, tmp_path):
    _patch_common(monkeypatch, tmp_path)
    result = runner.invoke(app, ["similarity", "check", "--json"])
    assert result.exit_code == 1
    payload = json.loads(result.output)
    assert payload["success"] is False


def test_check_title_missing_warning(monkeypatch, tmp_path):
    _patch_common(monkeypatch, tmp_path)
    monkeypatch.setattr("jfox.embedding_backend.get_backend", lambda: _StubBackend([1.0, 0.0, 0.0]))
    result = runner.invoke(app, ["similarity", "check", "--content", "正文", "--json"])
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert "title missing" in payload["warnings"][0]
