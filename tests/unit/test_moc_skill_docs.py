"""session-to-permanent 三平台与 jfox-moc 文档的 MOC 归属静态契约检查。"""

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SESSION_SKILLS = [
    REPO_ROOT / "skills-recommend/pi/jfox-session-to-permanent/SKILL.md",
    REPO_ROOT / "packages/cc-plugin/skills/session-to-permanent/SKILL.md",
    REPO_ROOT / "packages/kimi-plugin/skills/jfox-session-to-permanent/SKILL.md",
]
MOC_SKILL = REPO_ROOT / "skills-recommend/pi/jfox-moc/SKILL.md"


def test_session_skill_docs_describe_moc_ownership():
    for path in SESSION_SKILLS:
        text = path.read_text(encoding="utf-8")
        assert "type: structure" in text
        assert "jfox moc add-member" in text
        assert "每条新笔记" in text or "each new note" in text
        assert "失败" in text or "retry" in text.lower()


def test_moc_skill_doc_describes_member_commands():
    text = MOC_SKILL.read_text(encoding="utf-8")
    assert "jfox moc add-member" in text
    assert "jfox moc remove-member" in text
    assert "moc update" in text
