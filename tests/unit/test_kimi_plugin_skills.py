"""
测试类型: 单元测试
目标: packages/kimi-plugin/skills/ 中 skill 文档的结构与一致性
预估耗时: < 1 秒
依赖要求: 无外部依赖（纯文件读取）
"""

import re
from pathlib import Path

import pytest

pytestmark = [pytest.mark.unit, pytest.mark.fast]

REPO_ROOT = Path(__file__).resolve().parents[2]
SKILL_DIR = REPO_ROOT / "packages" / "kimi-plugin" / "skills"
SKILL_NAMES = [
    "using-jfox",
    "jfox-manage",
    "jfox-search",
    "jfox-ingest",
    "jfox-organize",
    "jfox-session-summary",
]


def _skill_path(name: str) -> Path:
    return SKILL_DIR / name / "SKILL.md"


@pytest.mark.parametrize("name", SKILL_NAMES)
def test_skill_file_exists(name):
    path = _skill_path(name)
    assert path.is_file(), f"expected skill at {path}"


@pytest.mark.parametrize("name", SKILL_NAMES)
def test_frontmatter_has_required_fields(name):
    text = _skill_path(name).read_text(encoding="utf-8")
    m = re.match(r"^---\n(.*?)\n---", text, re.DOTALL)
    assert m, f"{name} has no YAML frontmatter"
    fm = m.group(1)
    assert re.search(
        r"^name:\s*" + re.escape(name) + r"\s*$", fm, re.MULTILINE
    ), f"{name} frontmatter name mismatch"
    assert re.search(r"^description:", fm, re.MULTILINE), f"{name} missing description"


@pytest.mark.parametrize("name", SKILL_NAMES)
def test_no_cc_plugin_style_skill_refs(name):
    """kimi-plugin 内部应统一使用 /skill:jfox-* 语法，不应出现 CC 插件的 /jfox:* 引用。"""
    text = _skill_path(name).read_text(encoding="utf-8")
    bad_refs = re.findall(r"/jfox:[a-z-]+", text)
    assert not bad_refs, f"{name} contains CC-style skill refs: {bad_refs}"


@pytest.mark.parametrize("name", SKILL_NAMES)
def test_command_examples_prefer_json_shorthand(name):
    """命令示例中应使用 --json 简写，保持 kimi-plugin 内一致。"""
    text = _skill_path(name).read_text(encoding="utf-8")
    # 排除说明性文字（允许提到 `--format json` 选项本身）
    # 这里只检查反引号或代码块里的实际命令
    bad_commands = re.findall(r"jfox\s+\S+[^`\n]*--format\s+json", text)
    # using-jfox 的通用约定段落允许出现 "--format json 或 --json"
    if name == "using-jfox":
        bad_commands = [c for c in bad_commands if "或" not in c]
    assert not bad_commands, f"{name} uses --format json in command examples: {bad_commands}"


def test_manage_skill_has_parallel_health_check_guidance():
    """jfox-manage §5.1 应包含 AgentSwarm 并行采集指标的指导。"""
    text = _skill_path("jfox-manage").read_text(encoding="utf-8")
    section_match = re.search(r"### 5\.1.*?### 5\.2", text, re.DOTALL)
    assert section_match, "jfox-manage §5.1 not found"
    section = section_match.group(0)
    assert "AgentSwarm" in section, "jfox-manage §5.1 missing AgentSwarm guidance"
    assert "并行" in section, "jfox-manage §5.1 missing parallel execution guidance"


def test_organize_skill_has_parallel_orphan_suggest_links_guidance():
    """jfox-organize Step 3 应包含对多 orphan 并行 suggest-links 的指导。"""
    text = _skill_path("jfox-organize").read_text(encoding="utf-8")
    section_match = re.search(
        r"## Step 3: 图谱优化.*?(## 直接创建笔记|## 命令参考)", text, re.DOTALL
    )
    assert section_match, "jfox-organize Step 3 not found"
    section = section_match.group(0)
    assert "AgentSwarm" in section, "jfox-organize Step 3 missing AgentSwarm guidance"
    assert "suggest-links" in section, "jfox-organize Step 3 missing suggest-links guidance"
    assert "串行" in section, "jfox-organize Step 3 missing serial edit warning"


def test_plugin_version_bumped():
    """kimi.plugin.json 版本号应为有效语义化版本。"""
    manifest = REPO_ROOT / "packages" / "kimi-plugin" / "kimi.plugin.json"
    assert manifest.is_file(), "kimi.plugin.json missing"
    text = manifest.read_text(encoding="utf-8")
    m = re.search(r'"version":\s*"([^"]+)"', text)
    assert m, "kimi.plugin.json missing version"
    version = m.group(1)
    parts = version.split(".")
    assert len(parts) == 3, f"version {version} is not semver-like"
    assert all(p.isdigit() for p in parts), f"version {version} contains non-numeric parts"
