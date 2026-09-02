from __future__ import annotations

import ast
from pathlib import Path

import pytest

from scripts.enum_coverage import (
    DocumentedEnums,
    EnumCoverageError,
    extract_enum_values_from_ast,
    extract_model_enums,
    parse_readme_enums,
    validate_enum_coverage,
)

REPO_ROOT = Path(__file__).resolve().parents[2]


def _documented(note: tuple[str, ...], gem: tuple[str, ...]) -> DocumentedEnums:
    return DocumentedEnums(note_types=note, gem_levels=gem)


CURRENT_NOTE = (
    "fleeting", "literature", "permanent", "session", "candidate", "structure",
)
CURRENT_GEM = ("chipped", "flawed", "normal", "flawless", "perfect")


def test_parse_current_readme_enums():
    text = (REPO_ROOT / "README.md").read_text(encoding="utf-8")

    parsed = parse_readme_enums(text)

    assert parsed == _documented(CURRENT_NOTE, CURRENT_GEM)


def test_parse_readme_rejects_malformed_sections():
    good_table = (
        "## Note Model\n\n| Value | Meaning |\n|---|---|\n"
        "| `fleeting` | capture |\n| `permanent` | refined |\n\n"
        "```text\nchipped → flawed\n```\n"
    )
    with pytest.raises(EnumCoverageError, match="missing '## Note Model'"):
        parse_readme_enums("## Other\nstuff\n")
    with pytest.raises(EnumCoverageError, match="no 'Value' table"):
        parse_readme_enums("## Note Model\n\nno table here\n\n```text\na → b\n```\n")
    with pytest.raises(EnumCoverageError, match="no GemLevel arrow chain"):
        parse_readme_enums("## Note Model\n\n| Value |\n|---|\n| `a` |\n")
    with pytest.raises(EnumCoverageError, match="malformed Note Model table row"):
        parse_readme_enums(
            "## Note Model\n\n| Value |\n|---|\n| plain |\n\n```text\na → b\n```\n"
        )
    assert parse_readme_enums(good_table) == _documented(
        ("fleeting", "permanent"), ("chipped", "flawed")
    )


def test_parse_readme_ignores_explanatory_inline_code():
    text = (
        "## Note Model\n\n| Value |\n|---|\n| `a` |\n\n"
        "```text\nx → y\n```\n\n- `a` appears again in prose but must not duplicate.\n"
    )

    parsed = parse_readme_enums(text)

    assert parsed == _documented(("a",), ("x", "y"))


def test_extract_model_enums_current():
    values = extract_model_enums(REPO_ROOT / "jfox" / "models.py")

    assert values == _documented(CURRENT_NOTE, CURRENT_GEM)


def test_extract_enum_values_from_ast_requires_both_classes():
    tree = ast.parse("class NoteType:\n    A = 'a'\n")

    with pytest.raises(EnumCoverageError, match="missing enum class"):
        extract_enum_values_from_ast(tree)


def test_extract_enum_values_from_ast_rejects_non_string_members():
    tree = ast.parse("class NoteType:\n    A = 'a'\nclass GemLevel:\n    B = 1\n")

    with pytest.raises(EnumCoverageError, match="GemLevel.B must be a string literal"):
        extract_enum_values_from_ast(tree)


def test_extract_enum_values_from_ast_preserves_source_order():
    tree = ast.parse(
        "class NoteType:\n    SECOND = 'b'\n    FIRST = 'a'\n"
        "class GemLevel:\n    X = 'x'\n"
    )

    values = extract_enum_values_from_ast(tree)

    assert values["NoteType"] == ("b", "a")
    assert values["GemLevel"] == ("x",)


def test_missing_note_type_is_actionable():
    with pytest.raises(EnumCoverageError, match=r"NoteType.*add.*structure.*README"):
        validate_enum_coverage(
            _documented(CURRENT_NOTE, CURRENT_GEM),
            _documented(CURRENT_NOTE[:-1], CURRENT_GEM),
        )


def test_missing_gem_level_is_actionable():
    with pytest.raises(EnumCoverageError, match=r"GemLevel.*add.*perfect.*README"):
        validate_enum_coverage(
            _documented(CURRENT_NOTE, CURRENT_GEM),
            _documented(CURRENT_NOTE, CURRENT_GEM[:-1]),
        )


def test_stale_note_type_is_actionable():
    with pytest.raises(EnumCoverageError, match=r"NoteType.*remove stale.*legacy"):
        validate_enum_coverage(
            _documented(CURRENT_NOTE, CURRENT_GEM),
            _documented(CURRENT_NOTE + ("legacy",), CURRENT_GEM),
        )


def test_stale_gem_level_is_actionable():
    with pytest.raises(EnumCoverageError, match=r"GemLevel.*remove stale.*ancient"):
        validate_enum_coverage(
            _documented(CURRENT_NOTE, CURRENT_GEM),
            _documented(CURRENT_NOTE, ("ancient",) + CURRENT_GEM),
        )


def test_duplicate_documented_value_is_rejected():
    with pytest.raises(EnumCoverageError, match=r"duplicate documented value 'permanent'"):
        validate_enum_coverage(
            _documented(CURRENT_NOTE, CURRENT_GEM),
            _documented(CURRENT_NOTE + ("permanent",), CURRENT_GEM),
        )


def test_gem_level_order_is_enforced():
    reordered = (CURRENT_GEM[1], CURRENT_GEM[0]) + CURRENT_GEM[2:]
    with pytest.raises(EnumCoverageError, match=r"GemLevel.*order"):
        validate_enum_coverage(
            _documented(CURRENT_NOTE, CURRENT_GEM),
            _documented(CURRENT_NOTE, reordered),
        )


def test_aligned_values_pass():
    validate_enum_coverage(
        _documented(CURRENT_NOTE, CURRENT_GEM),
        _documented(tuple(sorted(CURRENT_NOTE)), CURRENT_GEM),
    )
