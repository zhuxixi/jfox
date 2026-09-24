"""
测试类型: 单元测试
目标功能: #549 路径语义两分法纯函数层（A1/A2）
预估耗时: < 1秒
依赖要求: 无 IO/KB，仅 mock config.notes_dir

验证 Note 的三件套：
1. expected_filepath 按当前字段现算规则路径（不看 _filepath pin）
2. filepath 钉/非钉两态（pin 优先，否则规则路径）
3. from_markdown 有 filepath 时钉住真实路径，无 filepath 时保持不钉
"""

from datetime import datetime
from pathlib import Path
from unittest.mock import patch

import pytest

from jfox.models import Note, NoteType

pytestmark = [pytest.mark.unit, pytest.mark.fast]

_NOTE_ID = "20250322143022"


def _make_note(note_type: NoteType, title: str, topic=None) -> Note:
    """构造不落盘的 Note 对象（_filepath 保持 None）"""
    return Note(
        id=_NOTE_ID,
        title=title,
        content="正文",
        type=note_type,
        created=datetime(2025, 3, 22, 14, 30, 22),
        updated=datetime(2025, 3, 22, 14, 30, 22),
        topic=topic,
    )


@pytest.fixture
def notes_root(tmp_path):
    """隔离 notes_dir：expected_filepath / filepath（未钉时）都指向它"""
    root = tmp_path / "notes"
    root.mkdir()
    with patch("jfox.config.config") as mock_config:
        mock_config.notes_dir = root
        yield root


class TestExpectedFilepath:
    """A1：expected_filepath 三分支——按当前字段现算，永不看 pin"""

    def test_permanent_uses_title_slug(self, notes_root):
        """A1：permanent 的规则路径为 notes_dir/permanent/{id}-{slug}.md"""
        n = _make_note(NoteType.PERMANENT, "Path Rules Alpha")
        assert n.expected_filepath == notes_root / "permanent" / f"{_NOTE_ID}-path-rules-alpha.md"

    def test_session_uses_topic(self, notes_root):
        """A1：session 的规则路径文件名由 topic 派生"""
        n = _make_note(NoteType.SESSION, "Session Title", topic="Topic Gamma")
        assert n.expected_filepath == notes_root / "session" / f"{_NOTE_ID}-topic-gamma.md"

    def test_session_without_topic_falls_back_to_title(self, notes_root):
        """A1：session 无 topic 时规则路径文件名回退到 title 派生"""
        n = _make_note(NoteType.SESSION, "Session Title", topic=None)
        assert n.expected_filepath == notes_root / "session" / f"{_NOTE_ID}-session-title.md"

    def test_fleeting_uses_dash_form(self, notes_root):
        """A1：fleeting 的规则路径文件名为 {id[:8]}-{id[8:]}.md 短横线形式"""
        n = _make_note(NoteType.FLEETING, "Fleeting Title")
        assert n.expected_filepath == notes_root / "fleeting" / "20250322-143022.md"

    def test_expected_filepath_ignores_pin(self, notes_root):
        """A1：set_filepath 钉住后 expected_filepath 不变，filepath 随 pin 变"""
        n = _make_note(NoteType.PERMANENT, "Path Rules Alpha")
        rule_path = n.expected_filepath

        pin = Path("/somewhere/else/renamed-on-disk.md")
        n.set_filepath(pin)

        assert n.expected_filepath == rule_path  # 规则路径无视 pin
        assert n.filepath == pin  # filepath 优先返回 pin


class TestFromMarkdownPin:
    """A2：from_markdown 的钉/不钉行为"""

    MD = (
        "---\n"
        f"id: '{_NOTE_ID}'\n"
        "title: Pin Probe One\n"
        "type: permanent\n"
        "created: '2025-03-22T14:30:22'\n"
        "updated: '2025-03-22T14:30:22'\n"
        "tags: []\n"
        "links: []\n"
        "backlinks: []\n"
        "---\n\n"
        "# Pin Probe One\n\n正文\n"
    )

    def test_with_filepath_pins_it(self):
        """A2：from_markdown 带 filepath 时 note.filepath 等于传入的真实路径"""
        on_disk = Path("/tmp/kb/permanent/20250322143022-renamed-on-disk.md")
        n = Note.from_markdown(self.MD, filepath=on_disk)
        assert n.filepath == on_disk

    def test_without_filepath_stays_unpinned(self, notes_root):
        """A2：from_markdown 不带 filepath 时 filepath 等于规则派生路径"""
        n = Note.from_markdown(self.MD)
        assert n.filepath == n.expected_filepath
        assert n.filepath == notes_root / "permanent" / f"{_NOTE_ID}-pin-probe-one.md"
