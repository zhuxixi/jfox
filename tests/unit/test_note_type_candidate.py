"""验证 NoteType.CANDIDATE 与 GemLevel 枚举。"""

from jfox.models import GemLevel, NoteType


def test_candidate_note_type():
    assert NoteType.CANDIDATE.value == "candidate"


def test_gem_level_enum_has_5_levels():
    assert [g.value for g in GemLevel] == ["chipped", "flawed", "normal", "flawless", "perfect"]


def test_gem_level_flawed():
    assert GemLevel.FLAWED.value == "flawed"
