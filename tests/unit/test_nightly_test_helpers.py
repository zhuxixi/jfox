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


def test_compute_signature_large_set_order_invariant():
    """失败数 > top_n（15 项 vs top_n=10）时，不同输入顺序签名仍相同。

    回归 #263 review round 1：prior impl 用 `sorted(failures[:top_n])`，
    先按出现顺序截断再排序，输入顺序变化会导致截断到不同子集 → 签名不同，
    违反 spec §5「签名对相同失败集合与顺序无关」的去重承诺。正确实现
    `sorted(failures)[:top_n]` 在任意顺序下取到同一组字典序最小 top_n。
    """
    items = [f"tests/x.py::test_{i:02d}" for i in range(15)]
    forward = list(items)
    backward = list(reversed(items))
    shuffled = items[::2] + items[1::2]  # 奇偶重排，非纯反转
    assert compute_signature(forward) == compute_signature(backward)
    assert compute_signature(forward) == compute_signature(shuffled)


def test_compute_signature_top_n_caps():
    """spec: 排序后超出 top_n 的失败（字典序靠后）不影响签名。

    用零填充命名 test_00..test_19，确保字典序=数值序，test_10..test_19
    严格排在 test_00..test_09 之后，被 top_n 截断。
    """
    base = [f"tests/x.py::test_{i:02d}" for i in range(10)]
    extra = base + [f"tests/x.py::test_{i:02d}" for i in range(10, 20)]
    assert compute_signature(base, top_n=10) == compute_signature(extra, top_n=10)


def test_compute_signature_empty_input():
    """边界：空失败列表返回长度 12 的稳定签名。"""
    sig = compute_signature([])
    assert isinstance(sig, str)
    assert len(sig) == 12
    assert compute_signature([]) == sig  # 多次调用稳定


def test_compute_signature_top_n_zero():
    """边界：top_n=0 时签名仍与顺序无关、长度 12。"""
    items = [f"tests/x.py::test_{i:02d}" for i in range(5)]
    sig = compute_signature(items, top_n=0)
    assert isinstance(sig, str)
    assert len(sig) == 12
    assert compute_signature(list(reversed(items)), top_n=0) == sig
