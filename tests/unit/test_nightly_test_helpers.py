"""nightly_test_helpers 纯逻辑单测。"""

import sys
from pathlib import Path

# 让 tests 能 import scripts/ 下的模块
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))

from nightly_test_helpers import compute_signature, extract_failures


def test_extract_failures_parses_nodeids():
    output = (
        "==== FAILURES ====\n"
        "FAILED tests/test_core_workflow.py::TestDevelopPhase::test_emb - AssertionError\n"
        "PASSED tests/test_other.py::test_x\n"
        "FAILED tests/test_hybrid.py::TestSearch::test_integration - TypeError\n"
    )
    assert extract_failures(output) == [
        "tests/test_core_workflow.py::TestDevelopPhase::test_emb",
        "tests/test_hybrid.py::TestSearch::test_integration",
    ]


def test_extract_failures_dedup_keeps_order():
    output = (
        "FAILED tests/a.py::test_1 - x\n"
        "FAILED tests/a.py::test_1 - x\n"
        "FAILED tests/b.py::test_2 - y\n"
    )
    assert extract_failures(output) == ["tests/a.py::test_1", "tests/b.py::test_2"]


def test_extract_failures_empty_when_no_failure():
    assert extract_failures("===== 5 passed in 3s =====") == []


def test_compute_signature_order_invariant():
    a = compute_signature(["tests/c.py::t", "tests/a.py::t", "tests/b.py::t"])
    b = compute_signature(["tests/b.py::t", "tests/c.py::t", "tests/a.py::t"])
    assert a == b  # 排序后稳定
    assert len(a) == 12  # sha1[:12]


def test_compute_signature_top_n_caps():
    many = [f"tests/x.py::test_{i}" for i in range(20)]
    assert compute_signature(many, top_n=10) == compute_signature(many[:10], top_n=10)
