"""Static contracts for the pi-only codemode section (#585)."""

import re
from pathlib import Path

import pytest

pytestmark = [pytest.mark.unit, pytest.mark.fast]

REPO_ROOT = Path(__file__).resolve().parents[2]
SKILL_PI = REPO_ROOT / "skills-recommend/pi/jfox-session-to-permanent/SKILL.md"
SKILL_OTHER = [
    REPO_ROOT / "packages/cc-plugin/skills/session-to-permanent/SKILL.md",
    REPO_ROOT / "packages/kimi-plugin/skills/jfox-session-to-permanent/SKILL.md",
]

FENCE_RE = re.compile(r"```[a-z]*\n(.*?)```", re.DOTALL)


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def has_codemode_section(text: str) -> bool:
    return "## codemode 加速" in text and "codemode" in text.split("## codemode 加速", 1)[1]


def has_both_templates(text: str) -> bool:
    return "### 模板一" in text and "### 模板二" in text


def _fenced_blocks(text: str) -> list[str]:
    return FENCE_RE.findall(text)


def _section(text: str, heading: str) -> str:
    start = text.index(heading)
    rest = text[start:]
    nxt = re.search(r"\n### ", rest[1:])
    return rest if nxt is None else rest[: nxt.start() + 1]


def auto_tier_code_blocks_use_force(text: str) -> bool:
    section = _section(text, "### 模板二")
    return any("--force" in block for block in _fenced_blocks(section))


def template_two_uses_verdict(text: str) -> bool:
    section = _section(text, "### 模板二")
    blocks = _fenced_blocks(section)
    return any("similarity check" in b and "verdict" in b for b in blocks)


def template_one_is_data_only(text: str) -> bool:
    section = _section(text, "### 模板一")
    joined = "\n".join(_fenced_blocks(section))
    if "document" in joined or "--type permanent" in joined:
        return False
    if "suggest-links" in joined:
        return False
    return not any(word in joined for word in ("已覆盖", "可补充", "未记录"))


def test_pi_skill_has_codemode_section():
    text = _read(SKILL_PI)
    assert has_codemode_section(text)
    assert "fallback" in text.lower() or "不可用" in text


def test_pi_skill_has_both_templates():
    assert has_both_templates(_read(SKILL_PI))


@pytest.mark.parametrize("path", SKILL_OTHER, ids=lambda p: p.parent.name)
def test_other_platforms_have_no_codemode(path):
    assert "codemode" not in _read(path)


def test_auto_tier_template_keeps_dedup_gate():
    assert not auto_tier_code_blocks_use_force(_read(SKILL_PI))


def test_template_two_consumes_similarity_verdict():
    assert template_two_uses_verdict(_read(SKILL_PI))


def test_template_one_is_data_only():
    assert template_one_is_data_only(_read(SKILL_PI))


def uses_jq(text: str) -> bool:
    return "jq " in text


def test_pi_skill_has_no_jq_dependency():
    assert not uses_jq(_read(SKILL_PI))
