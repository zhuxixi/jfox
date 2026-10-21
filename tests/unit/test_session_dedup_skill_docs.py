"""Static contracts for the S2 dedup gate docs across three platforms."""

from pathlib import Path

import pytest

pytestmark = [pytest.mark.unit, pytest.mark.fast]

REPO_ROOT = Path(__file__).resolve().parents[2]
SESSION_SKILLS = [
    REPO_ROOT / "skills-recommend/pi/jfox-session-to-permanent/SKILL.md",
    REPO_ROOT / "packages/cc-plugin/skills/session-to-permanent/SKILL.md",
    REPO_ROOT / "packages/kimi-plugin/skills/jfox-session-to-permanent/SKILL.md",
]
COMMAND_REFS = [
    REPO_ROOT / "skills-recommend/pi/jfox-common/SKILL.md",
    REPO_ROOT / "packages/cc-plugin/skills/manage/SKILL.md",
    REPO_ROOT / "packages/kimi-plugin/skills/jfox-manage/SKILL.md",
]


def test_platform_docs_use_similarity_gate():
    for path in SESSION_SKILLS:
        text = path.read_text(encoding="utf-8")
        assert "jfox similarity check" in text
        assert "verdict=new" in text or "`verdict=new`" in text
        assert "unavailable" in text
        s2_rows = [line for line in text.splitlines() if "S2 去重余量" in line]
        assert s2_rows, f"{path}: missing S2 去重余量 row"
        for row in s2_rows:
            assert "`gray`" in row, f"{path}: S2 row missing gray verdict"
            assert "`covered`" in row, f"{path}: S2 row missing covered verdict"
        assert "0.5–0.65" not in text
        assert text.count("--mode semantic") == 0


def test_s2_recheck_is_pinned_to_similarity_gate():
    for path in SESSION_SKILLS:
        text = path.read_text(encoding="utf-8")
        assert "落库前重跑一次 `jfox similarity check`" in text


def test_command_references_list_similarity():
    for path in COMMAND_REFS:
        text = path.read_text(encoding="utf-8")
        assert "jfox similarity stats" in text
        assert "jfox similarity check" in text
