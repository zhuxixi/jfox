"""Static contracts for the pi-only codemode section (#585)."""

from pathlib import Path

import pytest

pytestmark = [pytest.mark.unit, pytest.mark.fast]

REPO_ROOT = Path(__file__).resolve().parents[2]
SKILL_PI = REPO_ROOT / "skills-recommend/pi/jfox-session-to-permanent/SKILL.md"
SKILL_OTHER = [
    REPO_ROOT / "packages/cc-plugin/skills/session-to-permanent/SKILL.md",
    REPO_ROOT / "packages/kimi-plugin/skills/jfox-session-to-permanent/SKILL.md",
]


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def has_codemode_section(text: str) -> bool:
    return "## codemode 加速" in text and "codemode" in text.split("## codemode 加速", 1)[1]


def has_both_templates(text: str) -> bool:
    return "### 模板一" in text and "### 模板二" in text


def test_pi_skill_has_codemode_section():
    text = _read(SKILL_PI)
    assert has_codemode_section(text)
    assert "fallback" in text.lower() or "不可用" in text


def test_pi_skill_has_both_templates():
    assert has_both_templates(_read(SKILL_PI))


@pytest.mark.parametrize("path", SKILL_OTHER, ids=lambda p: p.parent.name)
def test_other_platforms_have_no_codemode(path):
    assert "codemode" not in _read(path)
