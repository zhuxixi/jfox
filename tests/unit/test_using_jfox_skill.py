"""
测试类型: 单元测试
目标: cc-plugin using-jfox 总览/路由 skill 的设计契约（issue #243）
预估耗时: < 1 秒
依赖要求: 无外部依赖（纯文件读取，不需要知识库 / fixture）

守护的设计不变量（见 docs/superpowers/specs/2026-06-17-using-jfox-skill-design.md）：
  1. skill 文件存在，frontmatter 合法（name=using-jfox，description 非空）
  2. description 只含元意图触发词，不含与 5 个能力型 skill 竞争的强动词
  3. body 中指向 manage / organize 的指针锚点确实存在
"""

import re
from pathlib import Path

import pytest

pytestmark = [pytest.mark.unit, pytest.mark.fast]

REPO_ROOT = Path(__file__).resolve().parents[2]  # tests/unit/x.py -> repo root
SKILL_DIR = REPO_ROOT / "packages" / "cc-plugin" / "skills"
USING_JFOX = SKILL_DIR / "using-jfox" / "SKILL.md"


def _frontmatter(path: Path) -> str:
    """Return the raw YAML frontmatter block (text between the --- fences)."""
    text = path.read_text(encoding="utf-8")
    m = re.match(r"^---\n(.*?)\n---", text, re.DOTALL)
    assert m, f"{path} has no YAML frontmatter"
    return m.group(1)


def test_skill_file_exists():
    assert USING_JFOX.is_file(), f"expected skill at {USING_JFOX}"


def test_frontmatter_name():
    assert re.search(r"^name:\s*using-jfox\s*$", _frontmatter(USING_JFOX), re.MULTILINE)


def test_frontmatter_description_is_non_empty():
    fm = _frontmatter(USING_JFOX)
    m = re.search(r"^description:\s*\|?\s*\n(.+)", fm, re.MULTILINE | re.DOTALL)
    assert m and m.group(1).strip(), "description must be present and non-empty"


# 设计核心（#243）：description 绝不能携带 5 个能力型 skill 拥有的强动词，
# 否则会在 auto-discovery 路由时与它们竞争同一个意图。
@pytest.mark.parametrize(
    "verb",
    ["搜索", "查找", "导入", "整理", "保存会话", "创建知识库", "管理知识库", "健康检查"],
)
def test_description_has_no_competing_verbs(verb):
    assert verb not in _frontmatter(USING_JFOX), (
        f"competing verb {verb!r} must not appear in using-jfox frontmatter "
        f"(see spec Section 2 / issue #243)"
    )


@pytest.mark.parametrize("trigger", ["能做什么", "overview", "入门"])
def test_description_carries_meta_triggers(trigger):
    assert trigger in _frontmatter(USING_JFOX), f"description should carry meta trigger {trigger!r}"


def test_pointers_resolve():
    """body 指向 manage / organize 的锚点必须真实存在，避免路由到缺失章节。"""
    assert USING_JFOX.is_file()
    checks = [
        (SKILL_DIR / "manage" / "SKILL.md", "共享约定"),  # §4.1
        (SKILL_DIR / "manage" / "SKILL.md", "知识库路径"),  # §2
        (SKILL_DIR / "manage" / "SKILL.md", "健康检查"),  # §5
        (SKILL_DIR / "organize" / "SKILL.md", "Inbox"),  # Step 1
        (SKILL_DIR / "organize" / "SKILL.md", "提炼"),  # Step 2
    ]
    missing = [
        (str(p), anchor) for p, anchor in checks if anchor not in p.read_text(encoding="utf-8")
    ]
    assert not missing, f"pointers point at missing sections: {missing}"
