# MOC Create/Update Commands Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add `NoteType.STRUCTURE` and `jfox moc create` / `jfox moc update` commands that turn diagnose clusters into maintainable MOC notes.

**Architecture:** Pure logic (draft/diff) lives in `jfox/moc/draft.py`; disk-write + backlinks backfill lives in `jfox/moc/generate.py`; CLI shells live in `jfox/moc/cli.py` reusing the existing `diagnose_moc_density` service (which already provides the read-only Chroma snapshot path). CLI commands stay thin; all business logic is in testable impl functions that take an explicit `ZKConfig`.

**Tech Stack:** Python 3.10+, Typer, Rich, dataclasses, pytest + unittest.mock, CliRunner (typer.testing).

## Global Constraints

- Line length 100; format with `black`; lint with `ruff` (project defaults from pyproject.toml).
- Chinese docstrings/comments (project convention); English commit messages (conventional commits).
- CLI error paths exit code 1 via `_fail(message, output_format)` and raise `typer.Exit(code=1)`; JSON errors are `{"success": false, "error": "..."}`.
- Help-text contract tests assert exact strings — any help text change must update its contract test in the same task.
- `jfox moc` group is registered on the root app via `app.add_typer(moc_app, ...)`; import of `jfox.cli` must not load chromadb/networkx/numpy (lazy import, keep `TYPE_CHECKING` pattern).
- Run tests single-process; quick unit tests may run standalone (`pytest tests/unit/test_moc_draft.py -v`), never the full suite.
- Never `git add -A`; stage exact file paths per task.

---

### Task 1: Add NoteType.STRUCTURE and dynamic type lists in CLI help/errors

**Files:**
- Modify: `jfox/models.py:40-47`
- Modify: `jfox/cli.py` (4 hardcoded type-list sites: ~line 500, ~line 679, ~line 1068, ~line 1700, ~line 1804)
- Test: `tests/unit/test_note_type_structure.py`

**Interfaces:**
- Consumes: nothing.
- Produces:
  - `NoteType.STRUCTURE = "structure"` (enum member; value is the string `"structure"`).
  - `cli.py` module-level constant `_NOTE_TYPE_VALUES: str = ", ".join(t.value for t in NoteType)` and `_NOTE_TYPE_SLASH: str = "/".join(t.value for t in NoteType)` — later tasks reuse these strings.

- [ ] **Step 1: Write the failing tests**

```python
# tests/unit/test_note_type_structure.py
"""NoteType.STRUCTURE 与 CLI 类型文案动态化测试。"""
from __future__ import annotations

import re

import pytest
from typer.testing import CliRunner

from jfox.cli import _NOTE_TYPE_SLASH, _NOTE_TYPE_VALUES, app
from jfox.models import Note, NoteType, datetime

runner = CliRunner()


def test_note_type_structure_member_exists():
    assert NoteType.STRUCTURE.value == "structure"
    assert len([t for t in NoteType]) == 6


def test_structure_note_filename_uses_slug_branch():
    note = Note(
        id="20260822010101",
        title="Zima Workflow MOC",
        content="",
        type=NoteType.STRUCTURE,
        created=datetime(2026, 8, 22, 1, 1, 1),
        updated=datetime(2026, 8, 22, 1, 1, 1),
    )
    assert note.filename == "20260822010101-zima-workflow-moc.md"


def test_structure_note_markdown_roundtrip_keeps_links():
    note = Note(
        id="20260822010101",
        title="Zima Workflow MOC",
        content="## zima\n\n- [[Zima One]] — 2 links\n",
        type=NoteType.STRUCTURE,
        created=datetime(2026, 8, 22, 1, 1, 1),
        updated=datetime(2026, 8, 22, 1, 1, 1),
        links=["20260820010101"],
    )
    restored = Note.from_markdown(note.to_markdown())
    assert restored.type == NoteType.STRUCTURE
    assert restored.links == ["20260820010101"]
    assert restored.content == note.content


def _strip_ansi(text: str) -> str:
    return re.sub(r"\x1b\[[0-9;]*m", "", text)


def test_cli_type_lists_cover_all_six_types():
    assert _NOTE_TYPE_VALUES.split(", ") == ["fleeting", "literature", "permanent", "session", "candidate", "structure"]
    assert _NOTE_TYPE_SLASH == "fleeting/literature/permanent/session/candidate/structure"


def test_add_invalid_type_error_lists_all_six():
    result = runner.invoke(app, ["add", "hello", "--type", "nope"])
    output = _strip_ansi(result.output)
    assert result.exit_code != 0
    for expected in ("fleeting", "literature", "permanent", "session", "candidate", "structure"):
        assert expected in output


def test_add_type_help_lists_all_six():
    result = runner.invoke(app, ["add", "--help"])
    output = _strip_ansi(result.output)
    assert "fleeting/literature/permanent/session/candidate/structure" in output
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/unit/test_note_type_structure.py -v`
Expected: `test_note_type_structure_member_exists` FAIL (AttributeError: STRUCTURE), `test_cli_type_lists_cover_all_six_types` FAIL (ImportError or missing constant), `test_add_invalid_type_error_lists_all_six` FAIL (`structure`/`candidate` missing from message).

- [ ] **Step 3: Implement enum + dynamic constants**

In `jfox/models.py`, extend the enum:

```python
class NoteType(Enum):
    """笔记类型"""

    FLEETING = "fleeting"  # 闪念笔记
    LITERATURE = "literature"  # 文献笔记
    PERMANENT = "permanent"  # 永久笔记
    SESSION = "session"  # AI Agent 会话记录
    CANDIDATE = "candidate"  # AI 合成的候选知识宝石（破损级，待 L5 审阅）
    STRUCTURE = "structure"  # 地图型笔记（MOC），导航/组织层
```

In `jfox/cli.py`, after the `NoteType` import, add module constants:

```python
_NOTE_TYPE_VALUES = ", ".join(t.value for t in NoteType)
_NOTE_TYPE_SLASH = "/".join(t.value for t in NoteType)
```

Replace the 4 hardcoded sites (search for `fleeting, literature, permanent, session`):

- Error messages (3 sites, in `_add_note_impl`, `_search_impl`, `_edit_note_impl`):
  `f"Invalid note type: {note_type}. Use: fleeting, literature, permanent, session"` → `f"Invalid note type: {note_type}. Use: {_NOTE_TYPE_VALUES}"`
- Help texts (2 sites):
  `help="笔记类型 (fleeting/literature/permanent/session)"` → `help=f"笔记类型 ({_NOTE_TYPE_SLASH})"`
  `help="新类型 (fleeting/literature/permanent/session)"` → `help=f"新类型 ({_NOTE_TYPE_SLASH})"`

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/unit/test_note_type_structure.py -v`
Expected: all 7 PASS.

- [ ] **Step 5: Commit**

```bash
git add jfox/models.py jfox/cli.py tests/unit/test_note_type_structure.py
git commit -m "feat(models): add NoteType.STRUCTURE and dynamic CLI type lists"
```

---

### Task 2: Pure draft/diff logic in jfox/moc/draft.py

**Files:**
- Create: `jfox/moc/draft.py`
- Test: `tests/unit/test_moc_draft.py`

**Interfaces:**
- Consumes: `jfox.moc.cluster.ClusterMember`, `ClusterSummary`, `OrphanNote` (fields: `id`, `title`, `link_degree`, `mean_similarity`).
- Produces:
  - `DraftGroup(name: str, members: List[ClusterMember])`
  - `MocCreateDraft(title: str, groups: List[DraftGroup], orphan_bucket: List[OrphanNote], total_members: int)`
  - `build_moc_draft(cluster, tags_by_id, max_size, orphans=None, title=None) -> MocCreateDraft` — raises `ValueError` when `len(cluster.members) > max_size`.
  - `render_moc_content(draft) -> str` — Markdown body (no frontmatter, no `# title` heading; `create_note` adds those).
  - `MocUpdateDiff(add: List[ClusterMember], remove: List[str], kept: int)`
  - `build_update_diff(current_links, cluster_members, live_permanent_ids) -> MocUpdateDiff`

- [ ] **Step 1: Write the failing tests**

```python
# tests/unit/test_moc_draft.py
"""MOC 草稿构建与更新 diff 的纯逻辑测试。"""
from __future__ import annotations

import pytest

from jfox.moc.cluster import ClusterMember, ClusterSummary, OrphanNote
from jfox.moc.draft import (
    build_moc_draft,
    build_update_diff,
    render_moc_content,
)


def _member(nid: str, title: str, degree: int = 2, sim: float = 0.8) -> ClusterMember:
    return ClusterMember(id=nid, title=title, link_degree=degree, mean_similarity=sim)


def _cluster() -> ClusterSummary:
    hub = _member("1", "Zima Hub", degree=10, sim=0.95)
    members = [
        hub,
        _member("2", "Zima CR Flow", degree=5, sim=0.9),
        _member("3", "Zima Gem V2", degree=3, sim=0.85),
        _member("4", "Zima MVP Plan", degree=1, sim=0.7),
        _member("5", "Misc Note", degree=0, sim=0.6),
    ]
    return ClusterSummary(size=len(members), members=members, hub=hub)


def _tags() -> dict:
    return {
        "1": ["zima", "cr"],
        "2": ["zima", "cr"],
        "3": ["zima", "gem"],
        "4": ["zima"],
        "5": ["misc"],
    }


def test_build_draft_groups_by_shared_tags():
    draft = build_moc_draft(_cluster(), _tags(), max_size=50)

    names = [g.name for g in draft.groups]
    assert names == ["zima", "cr"]  # zima: 4 条(>=min(2, 10%)), cr: 2 条; gem/misc 不成组
    zima_group = draft.groups[0]
    assert [m.id for m in zima_group.members][0] == "1"  # hub 置顶
    other_group = [g for g in draft.groups if g.name == "其他"][0]
    assert [m.id for m in other_group.members] == ["4", "5"]


def test_build_draft_default_title_derives_from_hub():
    draft = build_moc_draft(_cluster(), _tags(), max_size=50)
    assert draft.title == "Zima Hub MOC"


def test_build_draft_title_override():
    draft = build_moc_draft(_cluster(), _tags(), max_size=50, title="我的主题")
    assert draft.title == "我的主题"


def test_build_draft_rejects_oversized_cluster():
    with pytest.raises(ValueError, match="exceeds --max-size"):
        build_moc_draft(_cluster(), _tags(), max_size=4)


def test_build_draft_includes_orphans():
    orphans = [OrphanNote("9", "Orphan A", True, True)]
    draft = build_moc_draft(_cluster(), _tags(), max_size=50, orphans=orphans)
    assert [o.id for o in draft.orphan_bucket] == ["9"]


def test_render_content_has_groups_orphans_and_recent_section():
    orphans = [OrphanNote("9", "Orphan A", True, True)]
    draft = build_moc_draft(_cluster(), _tags(), max_size=50, orphans=orphans)
    content = render_moc_content(draft)

    assert "## zima" in content
    assert "- [[Zima Hub]] — 10 links" in content
    assert "## 其他" in content
    assert "## 待归类" in content
    assert "- [[Orphan A]] — 0 links" in content
    assert "## 近期活动" in content


def test_update_diff_adds_new_and_removes_dead_links():
    cluster = _cluster()
    diff = build_update_diff(
        current_links=["1", "2", "99"],  # 99 已死
        cluster_members=cluster.members,
        live_permanent_ids={"1", "2", "3", "4", "5"},
    )
    assert [m.id for m in diff.add] == ["3", "4", "5"]
    assert diff.remove == ["99"]
    assert diff.kept == 2
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/unit/test_moc_draft.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'jfox.moc.draft'`.

- [ ] **Step 3: Implement jfox/moc/draft.py**

```python
"""MOC 草稿构建与更新 diff 的纯逻辑。

本模块不含 I/O：不读索引、不写文件、不调用向量后端。
create/update 命令共享这些函数，便于单元测试。
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Sequence, Set

from .cluster import ClusterMember, ClusterSummary, OrphanNote

# 分组所需 tag 覆盖簇成员的最小比例（与最小计数 2 取 max）。
_GROUP_MIN_SHARE = 0.1
_OTHER_GROUP = "其他"
_ORPHAN_SECTION = "待归类"
_RECENT_SECTION = "近期活动"


@dataclass
class DraftGroup:
    """MOC 草稿中的一个成员分组。"""

    name: str
    members: List[ClusterMember] = field(default_factory=list)


@dataclass
class MocCreateDraft:
    """MOC 创建草稿：标题 + 分组 + 孤儿桶。"""

    title: str
    groups: List[DraftGroup] = field(default_factory=list)
    orphan_bucket: List[OrphanNote] = field(default_factory=list)
    total_members: int = 0


def build_moc_draft(
    cluster: ClusterSummary,
    tags_by_id: Dict[str, List[str]],
    max_size: int,
    orphans: Optional[List[OrphanNote]] = None,
    title: Optional[str] = None,
) -> MocCreateDraft:
    """把诊断簇渲染成 MOC 草稿。

    规则：
    - 簇 size 超过 max_size 时拒绝（ValueError），提示提高阈值拆分。
    - 成员按共享 tag 分组：tag 计数 >= max(2, 10% * size) 成组，余下「其他」。
    - 组内 hub 置顶，其余按 mean_similarity 降序。
    """
    members = list(cluster.members)
    if len(members) > max_size:
        raise ValueError(
            f"Cluster size {len(members)} exceeds --max-size {max_size}; "
            "raise --threshold to split the cluster or pass a larger --max-size explicitly"
        )

    hub = cluster.hub
    default_title = f"{hub.title} MOC" if hub is not None else f"MOC {len(members)} notes"
    draft_title = title if title else default_title

    # 共享 tag 计数
    tag_counts: Counter = Counter(
        tag for member in members for tag in tags_by_id.get(member.id, [])
    )
    min_share = max(2, int(_GROUP_MIN_SHARE * len(members)))
    grouped_tags = sorted(tag for tag, count in tag_counts.items() if count >= min_share)

    # 分组（hub 置顶 + mean_similarity 降序）
    groups: List[DraftGroup] = []
    for tag in grouped_tags:
        group_members = sorted(
            [m for m in members if tag in tags_by_id.get(m.id, [])],
            key=lambda m: (m.id != (hub.id if hub else ""), -m.mean_similarity),
        )
        groups.append(DraftGroup(name=tag, members=group_members))

    other_members = [
        m for m in members if all(tag not in tags_by_id.get(m.id, []) for tag in grouped_tags)
    ]
    other_members.sort(key=lambda m: (m.id != (hub.id if hub else ""), -m.mean_similarity))
    if other_members:
        groups.append(DraftGroup(name=_OTHER_GROUP, members=other_members))

    return MocCreateDraft(
        title=draft_title,
        groups=groups,
        orphan_bucket=list(orphans or []),
        total_members=len(members),
    )


def render_moc_content(draft: MocCreateDraft) -> str:
    """渲染 MOC 正文（不含 frontmatter 与标题行，create_note 负责补全）。

    小节顺序：各 tag 分组 → 「待归类」（孤儿）→ 「近期活动」占位。
    """
    lines: List[str] = []
    for group in draft.groups:
        lines.append(f"## {group.name}")
        lines.append("")
        for member in group.members:
            lines.append(f"- [[{member.title}]] — {member.link_degree} links")
        lines.append("")

    if draft.orphan_bucket:
        lines.append(f"## {_ORPHAN_SECTION}")
        lines.append("")
        for orphan in draft.orphan_bucket:
            lines.append(f"- [[{orphan.title}]] — {orphan.link_degree} links")
        lines.append("")

    lines.append(f"## {_RECENT_SECTION}")
    lines.append("")
    return "\n".join(lines)


@dataclass
class MocUpdateDiff:
    """MOC 更新 diff：建议新增的簇成员与应摘除的死链。"""

    add: List[ClusterMember] = field(default_factory=list)
    remove: List[str] = field(default_factory=list)
    kept: int = 0


def build_update_diff(
    current_links: Sequence[str],
    cluster_members: Sequence[ClusterMember],
    live_permanent_ids: Set[str],
) -> MocUpdateDiff:
    """对比 MOC 现有 links 与当前簇成员。

    - add：簇内但不在 links 中的 live 成员。
    - remove：links 中已不在 live_permanent_ids 的死链（已归档/已删除）。
    - kept：links 与簇成员的交集数。语义漂移不自动摘除（人工判断）。
    """
    member_ids = {m.id for m in cluster_members}
    current = set(current_links)
    remove = sorted(mid for mid in current if mid not in live_permanent_ids)
    add = [m for m in cluster_members if m.id not in current]
    kept = len(current & member_ids)
    return MocUpdateDiff(add=add, remove=remove, kept=kept)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/unit/test_moc_draft.py -v`
Expected: all 8 PASS. If the tag-group expectation mismatches, adjust `_GROUP_MIN_SHARE` logic (not the test) and re-run.

- [ ] **Step 5: Commit**

```bash
git add jfox/moc/draft.py tests/unit/test_moc_draft.py
git commit -m "feat(moc): add pure draft/diff logic for MOC create and update"
```

---

### Task 3: Disk-write + backlinks backfill in jfox/moc/generate.py

**Files:**
- Create: `jfox/moc/generate.py`
- Test: `tests/unit/test_moc_generate.py`

**Interfaces:**
- Consumes: `MocCreateDraft`, `DraftGroup` (Task 2); `jfox.note.create_note` (writes `notes/structure/...` and indexes), `jfox.note.load_note_by_id`, `jfox.note._atomic_write`, `jfox.note_index.get_note_index().update_note_meta`; module-level `jfox.config.config` must point at the target KB (tests use `use_kb` or monkeypatch).
- Produces:
  - `write_moc(draft) -> Note` — creates the structure note (title from draft, tags `["moc"]`, links = sorted member ids) and backfills member backlinks. Returns the created `Note`.
  - `backfill_moc_backlinks(moc_note, member_ids) -> None` — adds `moc_note.id` to each member's `backlinks` (incremental, same pattern as `promote_note`); single-member failure logs a warning, does not raise.
  - `remove_moc_backlinks(moc_id, member_ids) -> None` — removes `moc_id` from each member's `backlinks` (used by update).
  - `MOC_TAG = "moc"`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/unit/test_moc_generate.py
"""MOC 写盘与 backlinks 回填测试（进程内，mock embedding）。"""
from __future__ import annotations

import numpy as np
import pytest

from jfox.moc.cluster import ClusterMember, ClusterSummary, OrphanNote
from jfox.moc.draft import build_moc_draft
from jfox.moc.generate import MOC_TAG, backfill_moc_backlinks, remove_moc_backlinks, write_moc
from jfox.models import NoteType
from jfox.note import load_note_by_id, list_notes

MEMBER_IDS = ["20260820000001", "20260820000002"]


@pytest.fixture
def seeded_kb(tmp_path, monkeypatch):
    """初始化最小 KB：2 条 permanent + mock embedding 后端。"""
    from jfox.config import ZKConfig, use_kb

    cfg = ZKConfig(base_dir=tmp_path)
    cfg.ensure_dirs()
    # 手动写两条 permanent（不经过 CLI，避免依赖真实模型）
    from jfox.models import Note
    from jfox.note import _atomic_write, get_note_index

    now = Note.__annotations__ and None  # noqa: 占位，见下方真实实现
    for nid, title, tag in [
        ("20260820000001", "Zima One", "zima"),
        ("20260820000002", "Zima Two", "zima"),
    ]:
        note = Note(
            id=nid,
            title=title,
            content=f"content of {title}",
            type=NoteType.PERMANENT,
            created=datetime(2026, 8, 20),
            updated=datetime(2026, 8, 20),
            tags=[tag],
        )
        note.set_filepath(cfg.notes_dir / "permanent" / f"{nid}-{title.lower().replace(' ', '-')}.md")
        _atomic_write(note.filepath, note.to_markdown())
    get_note_index(cfg).rebuild()

    monkeypatch.setattr("jfox.config.config", cfg)
    yield cfg
```

Real implementation of `seeded_kb` (replace the placeholder lines above — use `datetime` import):

```python
@pytest.fixture
def seeded_kb(tmp_path, monkeypatch):
    """初始化最小 KB：2 条 permanent + mock embedding 后端。"""
    from datetime import datetime as dt

    from jfox.config import ZKConfig
    from jfox.models import Note
    from jfox.note import _atomic_write, get_note_index

    cfg = ZKConfig(base_dir=tmp_path)
    cfg.ensure_dirs()
    for nid, title, tag in [
        ("20260820000001", "Zima One", "zima"),
        ("20260820000002", "Zima Two", "zima"),
    ]:
        note = Note(
            id=nid,
            title=title,
            content=f"content of {title}",
            type=NoteType.PERMANENT,
            created=dt(2026, 8, 20, 0, 0, 0),
            updated=dt(2026, 8, 20, 0, 0, 0),
            tags=[tag],
        )
        note.set_filepath(cfg.notes_dir / "permanent" / f"{nid}-{title.lower().replace(' ', '-')}.md")
        _atomic_write(note.filepath, note.to_markdown())
    get_note_index(cfg).rebuild()

    monkeypatch.setattr("jfox.config.config", cfg)
    return cfg


def _draft(seeded_kb):
    members = [
        ClusterMember(id="20260820000001", title="Zima One", link_degree=1, mean_similarity=0.9),
        ClusterMember(id="20260820000002", title="Zima Two", link_degree=1, mean_similarity=0.8),
    ]
    cluster = ClusterSummary(size=2, members=members, hub=members[0])
    return build_moc_draft(cluster, {"20260820000001": ["zima"], "20260820000002": ["zima"]}, max_size=50)


def test_write_moc_creates_structure_note_with_links(seeded_kb):
    draft = _draft(seeded_kb)
    moc = write_moc(draft)

    assert moc.type == NoteType.STRUCTURE
    assert moc.tags == [MOC_TAG]
    assert moc.links == ["20260820000001", "20260820000002"]
    assert moc.filepath.exists()

    structure_notes = list_notes(note_type=NoteType.STRUCTURE, cfg=seeded_kb)
    assert len(structure_notes) == 1


def test_write_moc_backfills_member_backlinks(seeded_kb):
    draft = _draft(seeded_kb)
    moc = write_moc(draft)

    for mid in MEMBER_IDS:
        member = load_note_by_id(mid)
        assert moc.id in member.backlinks


def test_remove_moc_backlinks_strips_moc_id(seeded_kb):
    draft = _draft(seeded_kb)
    moc = write_moc(draft)
    remove_moc_backlinks(moc.id, MEMBER_IDS)

    for mid in MEMBER_IDS:
        member = load_note_by_id(mid)
        assert moc.id not in member.backlinks
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/unit/test_moc_generate.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'jfox.moc.generate'`.

- [ ] **Step 3: Implement jfox/moc/generate.py**

```python
"""MOC 写盘与 backlinks 回填/摘除。

写盘复用 note.create_note（落 structure/ 目录 + 进向量/BM25 索引）；
回填模式与 note.promote_note 的增量回填一致：单成员失败只 warning 不中断，
不对称时可用 `jfox index rebuild --backlinks` 全量重算兜底。
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import List, Sequence

from ..models import Note, NoteType
from .draft import MocCreateDraft, render_moc_content

logger = logging.getLogger(__name__)

MOC_TAG = "moc"


def write_moc(draft: MocCreateDraft) -> Note:
    """创建 structure 类型的 MOC 笔记并回填成员 backlinks。"""
    from ..note import create_note

    content = render_moc_content(draft)
    member_ids = sorted({m.id for group in draft.groups for m in group.members})
    moc = create_note(
        content,
        title=draft.title,
        note_type=NoteType.STRUCTURE,
        tags=[MOC_TAG],
        links=member_ids,
    )
    backfill_moc_backlinks(moc, member_ids)
    return moc


def backfill_moc_backlinks(moc_note: Note, member_ids: Sequence[str]) -> None:
    """把 MOC id 增量加进每个成员笔记的 backlinks。"""
    from ..note import _atomic_write, load_note_by_id
    from ..note_index import get_note_index

    now = datetime.now()
    index = get_note_index()
    for mid in member_ids:
        target = load_note_by_id(mid)
        if target is None or moc_note.id in target.backlinks:
            continue
        target.updated = now
        target.backlinks = sorted(set(target.backlinks + [moc_note.id]))
        try:
            _atomic_write(target.filepath, target.to_markdown())
            index.update_note_meta(target)
        except Exception as exc:  # 单成员失败不中断（与 promote 一致）
            logger.warning(f"Failed to backfill backlinks for MOC member {mid}: {exc}")


def remove_moc_backlinks(moc_id: str, member_ids: Sequence[str]) -> None:
    """把 MOC id 从成员笔记的 backlinks 摘除（update 摘除死链时用）。"""
    from ..note import _atomic_write, load_note_by_id
    from ..note_index import get_note_index

    now = datetime.now()
    index = get_note_index()
    for mid in member_ids:
        target = load_note_by_id(mid)
        if target is None or moc_id not in target.backlinks:
            continue
        target.updated = now
        target.backlinks = [b for b in target.backlinks if b != moc_id]
        try:
            _atomic_write(target.filepath, target.to_markdown())
            index.update_note_meta(target)
        except Exception as exc:
            logger.warning(f"Failed to remove MOC backlink for member {mid}: {exc}")
```

Note: `load_note_by_id` returns None for dead links — but it may return archived notes. For update's dead-link detection we rely on `build_update_diff`'s `live_permanent_ids` (computed by the caller from the note index); `remove_moc_backlinks` here only edits backlinks of members that still exist.

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/unit/test_moc_generate.py -v`
Expected: all 3 PASS. Note the fixture monkeypatches `jfox.config.config`; `create_note`/`save_note` index paths need an embedding backend — if `get_vector_store()` fails without a daemon, patch `jfox.embedding_backend.get_backend` with a mock returning a random-vector backend (same as `conftest.mock_embedding_backend`).

- [ ] **Step 5: Commit**

```bash
git add jfox/moc/generate.py tests/unit/test_moc_generate.py
git commit -m "feat(moc): add MOC disk write with backlinks backfill"
```

---

### Task 4: `jfox moc create` command

**Files:**
- Modify: `jfox/moc/cli.py`
- Test: `tests/unit/test_moc_create_cli.py`

**Interfaces:**
- Consumes: `diagnose_moc_density` (existing lazy wrapper), `report_to_dict`/`_member_to_dict`/`_fail` (existing), `build_moc_draft`/`render_moc_content` (Task 2), `write_moc` (Task 3), `jfox.note_index.get_note_index`.
- Produces:
  - `create_cmd` Typer command registered on `moc_app`: `jfox moc create --threshold 0.65 --cluster 0 --max-size 50 [--title X] [--include-orphans] [--yes] [--kb K] [--format table|json]`
  - `draft_to_dict(draft, cluster) -> dict` — stable JSON contract:
    `{"threshold": float, "cluster": {"size": int, "hub": {...}}, "draft": {"title": str, "groups": [{"name": str, "members": [{...member}]}], "orphan_bucket": [...], "total_members": int}, "created": null | {"id": str, "filepath": str}, "warnings": [...]}`
  - `_create_impl(active_config, threshold, cluster_index, max_size, title, include_orphans, write: bool) -> tuple[dict, Optional[Note]]` — business logic, testable in-process.

- [ ] **Step 1: Write the failing tests**

```python
# tests/unit/test_moc_create_cli.py
"""jfox moc create 命令测试。"""
from __future__ import annotations

import json
import re
from unittest.mock import patch

from typer.testing import CliRunner

from jfox.cli import app
from jfox.moc.cluster import (
    ClusterMember,
    ClusterSummary,
    CoverageReport,
    MocDiagnoseReport,
    OrphanSummary,
    SuggestedReport,
    ThresholdSummary,
)

runner = CliRunner()
_ANSI_RE = re.compile(r"\x1b\[[0-9;]*m")


def _strip_ansi(text: str) -> str:
    return _ANSI_RE.sub("", text)


def _help_lines(output: str) -> list[str]:
    return [" ".join(_strip_ansi(line).split()) for line in output.splitlines() if line.strip()]


def _report() -> MocDiagnoseReport:
    hub = ClusterMember(id="1", title="Zima Hub", link_degree=10, mean_similarity=0.95)
    member = ClusterMember(id="2", title="Zima CR Flow", link_degree=5, mean_similarity=0.9)
    return MocDiagnoseReport(
        coverage=CoverageReport(filesystem=2, vector=2, vector_orphans=0, bm25=2),
        threshold_sweep=[ThresholdSummary(0.65, 1, 2, 0)],
        suggest=SuggestedReport(
            threshold=0.65,
            clusters=[ClusterSummary(size=2, members=[hub, member], hub=hub)],
        ),
        orphans=OrphanSummary(count=0),
        warnings=[],
    )


def test_moc_create_help_registers_exact_contract():
    result = runner.invoke(app, ["moc", "create", "--help"])

    assert result.exit_code == 0
    lines = _help_lines(result.output)
    assert "Usage: jfox moc create [OPTIONS]" in lines
    assert "从诊断主题簇生成 MOC 笔记草稿（dry-run 默认，--yes 落盘）。" in lines
    assert "--max-size" in " ".join(lines)
    assert "--include-orphans" in " ".join(lines)


def test_moc_group_help_lists_create_and_update():
    result = runner.invoke(app, ["moc", "--help"])

    assert result.exit_code == 0
    lines = _help_lines(result.output)
    assert "│ create 从诊断主题簇生成 MOC 笔记草稿（dry-run 默认，--yes 落盘）。 │" in lines
    assert "│ update 重扫主题簇，diff 现有 MOC 成员（增补新笔记、摘除死链）。 │" in lines


def test_create_dry_run_prints_draft_without_writing(tmp_path, monkeypatch):
    from jfox.config import ZKConfig

    cfg = ZKConfig(base_dir=tmp_path)
    cfg.ensure_dirs()
    monkeypatch.setattr("jfox.config.config", cfg)

    with patch("jfox.moc.cli.diagnose_moc_density", return_value=_report()):
        with patch("jfox.moc.cli.get_note_index") as mock_index:
            from jfox.note_index import NoteMeta

            mock_index.return_value.get_all_meta.return_value = [
                NoteMeta(id="1", title="Zima Hub", type=None, tags=["zima"]),
                NoteMeta(id="2", title="Zima CR Flow", type=None, tags=["zima", "cr"]),
            ]
            result = runner.invoke(app, ["moc", "create", "--format", "table"])

    assert result.exit_code == 0
    output = _strip_ansi(result.output)
    assert "Zima Hub MOC" in output
    assert "## zima" in output
    assert "- [[Zima Hub]] — 10 links" in output
    # dry-run 不落盘
    assert not list(tmp_path.glob("structure/*.md"))


def test_create_yes_writes_moc(tmp_path, monkeypatch):
    from jfox.config import ZKConfig

    cfg = ZKConfig(base_dir=tmp_path)
    cfg.ensure_dirs()
    monkeypatch.setattr("jfox.config.config", cfg)

    with patch("jfox.moc.cli.diagnose_moc_density", return_value=_report()):
        with patch("jfox.moc.cli.get_note_index") as mock_index, patch(
            "jfox.moc.cli.write_moc"
        ) as mock_write:
            from jfox.models import Note, NoteType
            from jfox.note_index import NoteMeta

            mock_index.return_value.get_all_meta.return_value = [
                NoteMeta(id="1", title="Zima Hub", type=None, tags=["zima"]),
                NoteMeta(id="2", title="Zima CR Flow", type=None, tags=["zima", "cr"]),
            ]
            fake_moc = Note(
                id="20260822000001",
                title="Zima Hub MOC",
                content="",
                type=NoteType.STRUCTURE,
                created=Note.__annotations__ and None,
                updated=Note.__annotations__ and None,
            )
            mock_write.return_value = fake_moc
            result = runner.invoke(app, ["moc", "create", "--yes", "--format", "json"])

    assert result.exit_code == 0
    payload = json.loads(_strip_ansi(result.output))
    assert payload["success"] is True
    assert payload["created"]["id"] == "20260822000001"
    assert mock_write.call_count == 1
```

Fix the `created=`/`updated=` lines when writing the real test file:

```python
from datetime import datetime as dt
...
            fake_moc = Note(
                id="20260822000001",
                title="Zima Hub MOC",
                content="",
                type=NoteType.STRUCTURE,
                created=dt(2026, 8, 22),
                updated=dt(2026, 8, 22),
            )
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/unit/test_moc_create_cli.py -v`
Expected: help contract tests FAIL (`No such command 'create'`).

- [ ] **Step 3: Implement create_cmd in jfox/moc/cli.py**

Append to `jfox/moc/cli.py` (imports at top):

```python
from ..models import Note, NoteType
from ..note_index import get_note_index
from .cluster import ClusterSummary, OrphanNote  # extend existing import if needed
from .draft import MocCreateDraft, build_moc_draft, render_moc_content  # type: ignore[import]
from .generate import write_moc  # type: ignore[import]
```

Command + helpers (place after `_render_table`, before `diagnose_cmd`):

```python
def draft_to_dict(
    threshold: float,
    cluster: ClusterSummary,
    draft: MocCreateDraft,
    created: Optional[dict] = None,
) -> dict[str, Any]:
    """把创建结果转成稳定的 JSON 契约。"""
    return {
        "threshold": threshold,
        "cluster": {
            "size": cluster.size,
            "hub": _member_to_dict(cluster.hub) if cluster.hub else None,
        },
        "draft": {
            "title": draft.title,
            "groups": [
                {"name": group.name, "members": [_member_to_dict(m) for m in group.members]}
                for group in draft.groups
            ],
            "orphan_bucket": [_member_to_dict(o) for o in draft.orphan_bucket],
            "total_members": draft.total_members,
        },
        "created": created,
        "warnings": [],
    }


def _render_draft(draft: MocCreateDraft, cluster: ClusterSummary) -> None:
    """table 格式的草稿预览。"""
    _console.print(f"Cluster size {cluster.size}; hub: {cluster.hub.title if cluster.hub else 'N/A'}")
    _console.print(f"MOC title: {draft.title}")
    for group in draft.groups:
        _console.print(f"## {group.name} ({len(group.members)})")
        for member in group.members:
            _console.print(f"- [[{member.title}]] — {member.link_degree} links")
    if draft.orphan_bucket:
        _console.print(f"## 待归类 ({len(draft.orphan_bucket)})")
        for orphan in draft.orphan_bucket:
            _console.print(f"- [[{orphan.title}]] — {orphan.link_degree} links")


def _create_impl(
    active_config: ZKConfig,
    threshold: float,
    cluster_index: int,
    max_size: int,
    title: Optional[str],
    include_orphans: bool,
    write: bool,
) -> tuple[dict, Optional[Note]]:
    """create 核心逻辑：诊断 → 选簇 → 草稿 → 可选落盘。"""
    report = diagnose_moc_density(
        active_config,
        thresholds=[threshold],
        min_size=2,
        suggest_threshold=threshold,
        top=cluster_index + 1,
    )
    suggest = report.suggest
    if suggest is None or cluster_index >= len(suggest.clusters):
        raise MocDiagnoseError(
            f"No cluster at index {cluster_index}; run `jfox moc diagnose` to see clusters"
        )
    cluster = suggest.clusters[cluster_index]
    note_index = get_note_index(active_config)
    tags_by_id = {meta.id: list(meta.tags) for meta in note_index.get_all_meta()}
    orphans = report.orphans.notes if include_orphans else None
    draft = build_moc_draft(cluster, tags_by_id, max_size, orphans=orphans, title=title)
    created = None
    if write:
        moc = write_moc(draft)
        created = {"id": moc.id, "filepath": str(moc.filepath)}
    return draft_to_dict(threshold, cluster, draft, created), moc if write else None


@moc_app.command(
    "create",
    help="从诊断主题簇生成 MOC 笔记草稿（dry-run 默认，--yes 落盘）。",
)
def create_cmd(
    threshold: float = typer.Option(0.65, "--threshold"),
    cluster_index: int = typer.Option(0, "--cluster"),
    max_size: int = typer.Option(50, "--max-size"),
    title: Optional[str] = typer.Option(None, "--title"),
    include_orphans: bool = typer.Option(False, "--include-orphans"),
    yes: bool = typer.Option(False, "--yes"),
    kb: Optional[str] = typer.Option(None, "--kb", "-k"),
    output_format: str = typer.Option("table", "--format", "-f"),
) -> None:
    """从诊断主题簇生成 MOC 笔记草稿。"""
    if output_format not in {"table", "json"}:
        _fail("format must be table or json", output_format)
    if not 0 < threshold < 1:
        _fail("threshold must be strictly between 0 and 1", output_format)
    if cluster_index < 0:
        _fail("cluster index must be >= 0", output_format)
    if max_size < 1:
        _fail("max_size must be at least 1", output_format)

    try:
        with use_kb(kb):
            active_config = ZKConfig.for_kb(config.base_dir)
            payload, moc = _create_impl(
                active_config, threshold, cluster_index, max_size, title, include_orphans, yes
            )
    except (MocDiagnoseError, ValueError, OSError) as exc:
        _fail(str(exc), output_format)

    if output_format == "json":
        _json_console.print(json.dumps(payload, ensure_ascii=False, indent=2), soft_wrap=True)
    else:
        draft_dict = payload["draft"]
        draft = MocCreateDraft(
            title=draft_dict["title"],
            groups=[],
            orphan_bucket=[],
            total_members=draft_dict["total_members"],
        )
        _render_draft(draft, None)  # table 渲染需要 draft 对象；重构为传 draft 与 cluster
```

> Implementation note: for the table render path, refactor `_create_impl` to also return `(draft, cluster)` or render the table from the payload dict. Simplest: return the draft object from `_create_impl` too, and have `create_cmd` call `_render_draft(draft, cluster)` directly. Adjust `_render_draft` signature to `(draft: MocCreateDraft, cluster: ClusterSummary)`. The test asserts on table output, so keep the rendered strings ("Cluster size 2; hub: Zima Hub", "## zima (2)", "- [[Zima Hub]] — 10 links").

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/unit/test_moc_create_cli.py -v`
Expected: all 5 PASS (fix table rendering details if contract strings mismatch).

- [ ] **Step 5: Commit**

```bash
git add jfox/moc/cli.py tests/unit/test_moc_create_cli.py
git commit -m "feat(moc): add moc create command with dry-run and --yes"
```

---

### Task 5: `jfox moc update` command

**Files:**
- Modify: `jfox/moc/cli.py`
- Test: `tests/unit/test_moc_update_cli.py`

**Interfaces:**
- Consumes: `diagnose_moc_density`, `build_update_diff` (Task 2), `remove_moc_backlinks`/`backfill_moc_backlinks` (Task 3), `jfox.note.list_notes(NoteType.STRUCTURE)`, `jfox.note.update_note`, `get_note_index`.
- Produces:
  - `update_cmd` Typer command: `jfox moc update [--id MOC_ID] [--threshold 0.65] [--yes] [--kb K] [--format table|json]`
  - `_update_impl(active_config, moc_id, threshold, apply: bool) -> list[dict]` — per-MOC diff payloads:
    `{"moc_id": str, "moc_title": str, "add": [{...member}], "remove": [str], "kept": int}`.
  - Matching rule: a MOC maps to the cluster with the largest `|links ∩ cluster member ids|`; intersection 0 → skipped with warning entry.

- [ ] **Step 1: Write the failing tests**

```python
# tests/unit/test_moc_update_cli.py
"""jfox moc update 命令测试。"""
from __future__ import annotations

import json
import re
from unittest.mock import patch

from typer.testing import CliRunner

from jfox.cli import app
from jfox.moc.cluster import (
    ClusterMember,
    ClusterSummary,
    CoverageReport,
    MocDiagnoseReport,
    OrphanSummary,
    SuggestedReport,
    ThresholdSummary,
)

runner = CliRunner()
_ANSI_RE = re.compile(r"\x1b\[[0-9;]*m")


def _strip_ansi(text: str) -> str:
    return _ANSI_RE.sub("", text)


def _report() -> MocDiagnoseReport:
    """簇含 1/2/3；links 里 99 是死链、2 在簇内、新成员 3。"""
    hub = ClusterMember(id="1", title="Zima Hub", link_degree=10, mean_similarity=0.95)
    two = ClusterMember(id="2", title="Zima CR Flow", link_degree=5, mean_similarity=0.9)
    three = ClusterMember(id="3", title="Zima Gem V2", link_degree=3, mean_similarity=0.85)
    return MocDiagnoseReport(
        coverage=CoverageReport(filesystem=3, vector=3, vector_orphans=0, bm25=3),
        threshold_sweep=[ThresholdSummary(0.65, 1, 3, 0)],
        suggest=SuggestedReport(
            threshold=0.65,
            clusters=[ClusterSummary(size=3, members=[hub, two, three], hub=hub)],
        ),
        orphans=OrphanSummary(count=0),
        warnings=[],
    )


def _moc_note():
    from datetime import datetime as dt

    from jfox.models import Note, NoteType

    return Note(
        id="20260822000001",
        title="Zima Hub MOC",
        content="",
        type=NoteType.STRUCTURE,
        created=dt(2026, 8, 22),
        updated=dt(2026, 8, 22),
        links=["1", "2", "99"],
    )


def test_moc_update_help_registers_exact_contract():
    result = runner.invoke(app, ["moc", "update", "--help"])

    assert result.exit_code == 0
    lines = [" ".join(_strip_ansi(l).split()) for l in result.output.splitlines() if l.strip()]
    assert "Usage: jfox moc update [OPTIONS]" in lines
    assert "重扫主题簇，diff 现有 MOC 成员（增补新笔记、摘除死链）。" in lines


def test_update_dry_run_shows_diff(tmp_path, monkeypatch):
    from jfox.config import ZKConfig

    cfg = ZKConfig(base_dir=tmp_path)
    cfg.ensure_dirs()
    monkeypatch.setattr("jfox.config.config", cfg)

    with patch("jfox.moc.cli.diagnose_moc_density", return_value=_report()):
        with patch("jfox.moc.cli.list_notes", return_value=[_moc_note()]):
            with patch("jfox.moc.cli.get_note_index") as mock_index:
                from jfox.note_index import NoteMeta

                mock_index.return_value.get_all_meta.return_value = [
                    NoteMeta(id="1", title="Zima Hub", type=None, tags=["zima"]),
                    NoteMeta(id="2", title="Zima CR Flow", type=None, tags=["zima"]),
                    NoteMeta(id="3", title="Zima Gem V2", type=None, tags=["zima"]),
                ]
                result = runner.invoke(app, ["moc", "update", "--format", "json"])

    assert result.exit_code == 0
    payload = json.loads(_strip_ansi(result.output))
    assert payload["success"] is True
    updates = payload["updates"]
    assert len(updates) == 1
    first = updates[0]
    assert first["moc_id"] == "20260822000001"
    assert [m["id"] for m in first["add"]] == ["3"]
    assert first["remove"] == ["99"]
    assert first["kept"] == 2
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/unit/test_moc_update_cli.py -v`
Expected: FAIL (`No such command 'update'`).

- [ ] **Step 3: Implement update_cmd in jfox/moc/cli.py**

```python
def _update_impl(
    active_config: ZKConfig,
    moc_id: Optional[str],
    threshold: float,
    apply: bool,
) -> tuple[list[dict], list[Note]]:
    """update 核心逻辑：诊断一次 → 每个 structure 笔记匹配簇 → diff → 可选应用。"""
    from ..note import list_notes, load_note_by_id, update_note
    from .draft import build_update_diff
    from .generate import backfill_moc_backlinks, remove_moc_backlinks

    if moc_id is not None:
        moc = load_note_by_id(moc_id)
        if moc is None:
            raise MocDiagnoseError(f"MOC note not found: {moc_id}")
        if moc.type != NoteType.STRUCTURE:
            raise MocDiagnoseError(f"Note {moc_id} is not a structure note (type={moc.type.value})")
        moc_notes = [moc]
    else:
        moc_notes = list_notes(note_type=NoteType.STRUCTURE, cfg=active_config)
    if not moc_notes:
        raise MocDiagnoseError("No structure notes found; run `jfox moc create` first")

    report = diagnose_moc_density(
        active_config, thresholds=[threshold], min_size=2, suggest_threshold=threshold, top=100
    )
    clusters = report.suggest.clusters if report.suggest is not None else []

    note_index = get_note_index(active_config)
    live_permanent_ids = {
        meta.id for meta in note_index.get_all_meta()
        if meta.type == NoteType.PERMANENT and not meta.archived
    }

    payloads: list[dict] = []
    changed: list[Note] = []
    for moc in moc_notes:
        current = set(moc.links)
        # 匹配：与 links 交集最大的簇
        best: Optional[ClusterSummary] = None
        best_overlap = -1
        for cluster in clusters:
            overlap = len(current & {m.id for m in cluster.members})
            if overlap > best_overlap:
                best_overlap = overlap
                best = cluster
        if best is None or best_overlap == 0:
            payloads.append({"moc_id": moc.id, "moc_title": moc.title,
                             "add": [], "remove": [], "kept": 0,
                             "warning": "no matching cluster; skipped"})
            continue

        diff = build_update_diff(moc.links, best.members, live_permanent_ids)
        payload = {
            "moc_id": moc.id,
            "moc_title": moc.title,
            "add": [_member_to_dict(m) for m in diff.add],
            "remove": list(diff.remove),
            "kept": diff.kept,
        }
        payloads.append(payload)

        if apply and (diff.add or diff.remove):
            add_ids = [m.id for m in diff.add]
            moc.links = sorted(set(moc.links + add_ids) - set(diff.remove))
            update_note(moc)
            backfill_moc_backlinks(moc, add_ids)
            remove_moc_backlinks(moc.id, diff.remove)
            changed.append(moc)

    return payloads, changed


@moc_app.command(
    "update",
    help="重扫主题簇，diff 现有 MOC 成员（增补新笔记、摘除死链）。",
)
def update_cmd(
    moc_id: Optional[str] = typer.Option(None, "--id", help="MOC 笔记 id（缺省=全部 structure）"),
    threshold: float = typer.Option(0.65, "--threshold"),
    yes: bool = typer.Option(False, "--yes"),
    kb: Optional[str] = typer.Option(None, "--kb", "-k"),
    output_format: str = typer.Option("table", "--format", "-f"),
) -> None:
    """重扫主题簇，diff 现有 MOC 成员。"""
    if output_format not in {"table", "json"}:
        _fail("format must be table or json", output_format)
    if not 0 < threshold < 1:
        _fail("threshold must be strictly between 0 and 1", output_format)

    try:
        with use_kb(kb):
            active_config = ZKConfig.for_kb(config.base_dir)
            payloads, changed = _update_impl(active_config, moc_id, threshold, yes)
    except (MocDiagnoseError, ValueError, OSError) as exc:
        _fail(str(exc), output_format)

    wrapper = {"success": True, "updates": payloads, "applied": len(changed) > 0}
    if output_format == "json":
        _json_console.print(json.dumps(wrapper, ensure_ascii=False, indent=2), soft_wrap=True)
    else:
        for payload in payloads:
            _console.print(f"[{payload['moc_id']}] {payload['moc_title']}")
            for member in payload["add"]:
                _console.print(f"  + [[{member['title']}]] ({member['id']})")
            for rid in payload["remove"]:
                _console.print(f"  - {rid} (dead link)")
            if not payload["add"] and not payload["remove"]:
                _console.print("  (no changes)")
            if payload.get("warning"):
                _console.print(f"  Warning: {payload['warning']}")
```

Add imports at top of `jfox/moc/cli.py`: `from ..models import Note, NoteType` and `from .cluster import ClusterSummary` (type-only import is fine under TYPE_CHECKING if only used in annotations — but `_update_impl` uses `ClusterSummary` only for typing, so keep it in the TYPE_CHECKING block).

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/unit/test_moc_update_cli.py -v`
Expected: both PASS. Also run the Task 4 help test — `test_moc_group_help_lists_create_and_update` now passes (update exists).

- [ ] **Step 5: Commit**

```bash
git add jfox/moc/cli.py tests/unit/test_moc_update_cli.py
git commit -m "feat(moc): add moc update command with cluster diff"
```

---

### Task 6: Integration test + README docs

**Files:**
- Test: `tests/unit/test_moc_integration.py`
- Modify: `README.md`

**Interfaces:**
- Consumes: everything from Tasks 1–5.
- Produces: end-to-end behavior proof (real KB, real files, mocked diagnose for determinism).

- [ ] **Step 1: Write the failing integration test**

```python
# tests/unit/test_moc_integration.py
"""MOC create/update 端到端集成测试（真实 KB 文件 + mock 诊断）。"""
from __future__ import annotations

from datetime import datetime as dt
from unittest.mock import patch

import pytest

from jfox.config import ZKConfig
from jfox.models import Note, NoteType
from jfox.moc.cluster import (
    ClusterMember,
    ClusterSummary,
    CoverageReport,
    MocDiagnoseReport,
    OrphanSummary,
    SuggestedReport,
    ThresholdSummary,
)
from jfox.moc.cli import _create_impl, _update_impl
from jfox.note import _atomic_write, get_note_index, list_notes


@pytest.fixture
def seeded_kb(tmp_path, monkeypatch):
    cfg = ZKConfig(base_dir=tmp_path)
    cfg.ensure_dirs()
    for nid, title in [
        ("20260820000001", "Zima One"),
        ("20260820000002", "Zima Two"),
    ]:
        note = Note(
            id=nid,
            title=title,
            content=f"content of {title}",
            type=NoteType.PERMANENT,
            created=dt(2026, 8, 20),
            updated=dt(2026, 8, 20),
            tags=["zima"],
        )
        slug = title.lower().replace(" ", "-")
        note.set_filepath(cfg.notes_dir / "permanent" / f"{nid}-{slug}.md")
        _atomic_write(note.filepath, note.to_markdown())
    get_note_index(cfg).rebuild()
    monkeypatch.setattr("jfox.config.config", cfg)
    return cfg


def _report(member_ids):
    members = [
        ClusterMember(id=nid, title=f"Note {nid}", link_degree=1, mean_similarity=0.9)
        for nid in member_ids
    ]
    cluster = ClusterSummary(size=len(members), members=members, hub=members[0])
    return MocDiagnoseReport(
        coverage=CoverageReport(filesystem=2, vector=2, vector_orphans=0, bm25=2),
        threshold_sweep=[ThresholdSummary(0.65, 1, len(members), 0)],
        suggest=SuggestedReport(threshold=0.65, clusters=[cluster]),
        orphans=OrphanSummary(count=0),
        warnings=[],
    )


def test_create_then_update_end_to_end(seeded_kb):
    # create
    with patch("jfox.moc.cli.diagnose_moc_density", return_value=_report(["20260820000001", "20260820000002"])):
        payload, moc = _create_impl(seeded_kb, 0.65, 0, 50, None, False, True)

    assert moc is not None
    assert moc.type == NoteType.STRUCTURE
    assert moc.filepath.exists()
    assert sorted(moc.links) == ["20260820000001", "20260820000002"]
    assert len(list_notes(note_type=NoteType.STRUCTURE, cfg=seeded_kb)) == 1

    # 新增第三条 permanent + 一条死链
    third = Note(
        id="20260820000003",
        title="Zima Three",
        content="content of Zima Three",
        type=NoteType.PERMANENT,
        created=dt(2026, 8, 21),
        updated=dt(2026, 8, 21),
        tags=["zima"],
    )
    third.set_filepath(seeded_kb.notes_dir / "permanent" / "20260820000003-zima-three.md")
    _atomic_write(third.filepath, third.to_markdown())
    moc.links = sorted(moc.links + ["20260820999999"])  # 死链
    from jfox.note import update_note

    update_note(moc)
    get_note_index(seeded_kb).rebuild()

    # update
    with patch(
        "jfox.moc.cli.diagnose_moc_density",
        return_value=_report(["20260820000001", "20260820000002", "20260820000003"]),
    ):
        payloads, changed = _update_impl(seeded_kb, moc.id, 0.65, True)

    assert len(payloads) == 1
    assert [m["id"] for m in payloads[0]["add"]] == ["20260820000003"]
    assert payloads[0]["remove"] == ["20260820999999"]

    updated_moc = list_notes(note_type=NoteType.STRUCTURE, cfg=seeded_kb)[0]
    assert "20260820000003" in updated_moc.links
    assert "20260820999999" not in updated_moc.links
```

- [ ] **Step 2: Run test to verify it fails (pre-Task-4 state) or passes now**

Run: `pytest tests/unit/test_moc_integration.py -v`
Expected: if run before Task 4/5 implementation this fails on import; after Tasks 1–5 it should PASS. If `update_note` inside `_update_impl` needs an embedding backend, patch `jfox.embedding_backend.get_backend` with the random-vector mock (as in conftest) inside the test fixture.

- [ ] **Step 3: Update README.md**

In the `### Search & Analysis` section (after the `jfox moc diagnose` row, if present, otherwise after `jfox graph` rows), add:

```markdown
| `jfox moc diagnose` | Diagnose permanent-note semantic density and MOC cluster suggestions |
| `jfox moc create --yes` | Create a structure (MOC) note from a diagnosed cluster (dry-run by default) |
| `jfox moc update` | Re-scan clusters and diff existing MOC members (add new, prune dead links) |
```

- [ ] **Step 4: Run the quick test subset**

Run: `pytest tests/unit/test_note_type_structure.py tests/unit/test_moc_draft.py tests/unit/test_moc_generate.py tests/unit/test_moc_create_cli.py tests/unit/test_moc_update_cli.py tests/unit/test_moc_integration.py -v`
Expected: all PASS. Also run `pytest tests/unit/test_moc_cli.py tests/unit/test_moc_cluster.py -v` (existing diagnose tests must stay green).

- [ ] **Step 5: Commit**

```bash
git add tests/unit/test_moc_integration.py README.md
git commit -m "test(moc): add create/update end-to-end test and README docs"
```

---

## Self-Review Notes (done by plan author)

- Spec coverage: D1 (Task 1), D2 (Tasks 4/5), D3 (Task 4 dry-run/--yes), D4 (Task 2 max_size guard), D5 (Task 2 grouping/rendering), D6 (Task 2 orphans + Task 5 live filter), D7 (Task 5 diff semantics), D8 (Task 3 backfill/remove), D9 (Tasks 4/5 reuse diagnose). Spec §7 test points all mapped.
- Placeholder scan: no TBD/TODO; each step has concrete code or exact commands.
- Type consistency: `build_moc_draft(cluster, tags_by_id, max_size, orphans=None, title=None)` signature consistent across Tasks 2–4; `build_update_diff(current_links, cluster_members, live_permanent_ids)` consistent across Tasks 2/5; `write_moc(draft) -> Note` consistent across Tasks 3/4.
