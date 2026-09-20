"""A3 (#519): 打包结构静态断言——核心依赖不含 sentence-transformers。"""

import sys
from pathlib import Path

import pytest

try:
    import tomllib
except ModuleNotFoundError:  # Python 3.10 无 stdlib tomllib；用例已由下方 skipif 拦截
    tomllib = None  # type: ignore[assignment]

pytestmark = pytest.mark.skipif(
    sys.version_info < (3, 11),
    reason="tomllib requires Python 3.11+ (#519 A3 runs on 3.11+)",
)

PYPROJECT = Path(__file__).resolve().parent.parent.parent / "pyproject.toml"


def _project() -> dict:
    with open(PYPROJECT, "rb") as f:
        return tomllib.load(f)["project"]


def _deps_of(section: str) -> list:
    return _project()["optional-dependencies"].get(section, [])


def test_core_deps_exclude_sentence_transformers():
    core = _project()["dependencies"]
    offenders = [d for d in core if d.lower().replace(" ", "").startswith("sentence-transformers")]
    assert offenders == [], f"核心依赖不应含 sentence-transformers: {offenders}"


def test_embed_extra_contains_sentence_transformers():
    embed = _deps_of("embed")
    assert any(
        d.lower().startswith("sentence-transformers") for d in embed
    ), "embed extra 应含 sentence-transformers"


def test_dev_extra_has_no_sentence_transformers():
    dev = _deps_of("dev")
    assert not any(
        d.lower().startswith("sentence-transformers") for d in dev
    ), "dev extra 不应含 sentence-transformers"
