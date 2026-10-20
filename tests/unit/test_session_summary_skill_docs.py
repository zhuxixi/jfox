"""session summary skill / 参数清单 / JSON schema 文档的字段断言。"""

from pathlib import Path

import pytest

pytestmark = [pytest.mark.unit, pytest.mark.fast]

ROOT = Path(__file__).resolve().parents[2]

SKILLS = [
    ROOT / "skills-recommend/pi/jfox-session-summary/SKILL.md",
    ROOT / "skills-recommend/kimi-cli/jfox-session-summary/SKILL.md",
    ROOT / "packages/cc-plugin/skills/session-summary/SKILL.md",
    ROOT / "packages/kimi-plugin/skills/jfox-session-summary/SKILL.md",
]

PARAM_LISTS = [
    ROOT / "skills-recommend/pi/jfox-common/SKILL.md",
    ROOT / "skills-recommend/kimi-cli/jfox-common/SKILL.md",
    ROOT / "packages/cc-plugin/skills/manage/SKILL.md",
    ROOT / "packages/kimi-plugin/skills/jfox-manage/SKILL.md",
]


@pytest.mark.parametrize("path", SKILLS, ids=lambda p: p.parent.name)
def test_session_skill_documents_agent_options(path):
    text = path.read_text(encoding="utf-8")
    for flag in ("--agent", "--session-path", "--agent-model"):
        assert flag in text, f"{path} 缺 {flag}"


@pytest.mark.parametrize("path", PARAM_LISTS, ids=lambda p: p.parent.name)
def test_param_lists_document_agent_options(path):
    text = path.read_text(encoding="utf-8")
    for flag in ("--agent", "--session-path", "--agent-model"):
        assert flag in text, f"{path} 缺 {flag}"


def test_pi_skill_uses_env_session_file():
    text = SKILLS[0].read_text(encoding="utf-8")
    assert "pi-coding-agent" in text
    assert "PI_SESSION_FILE" in text


def test_json_schema_docs_include_new_fields():
    text = (ROOT / "docs/json-schemas.md").read_text(encoding="utf-8")
    for field in ("agent", "session_file", "agent_model"):
        assert field in text
