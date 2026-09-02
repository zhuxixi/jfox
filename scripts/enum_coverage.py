"""Pure helpers checking README Note Model enums against jfox/models.py."""

from __future__ import annotations

import ast
import re
from dataclasses import dataclass
from pathlib import Path

README_SECTION_HEADING = "## Note Model"
NOTE_TYPE_TABLE_HEADER = "Value"
GEM_CHAIN_ARROW = "→"
_IDENTIFIER = re.compile(r"[a-z][a-z0-9_-]*")
_TABLE_ROW = re.compile(r"^\|\s*`([^`]+)`\s*\|")


class EnumCoverageError(ValueError):
    """Documented enum values diverge from models.py, or inputs are malformed."""


@dataclass(frozen=True)
class DocumentedEnums:
    note_types: tuple[str, ...]
    gem_levels: tuple[str, ...]


def extract_enum_values_from_ast(tree: ast.Module) -> dict[str, tuple[str, ...]]:
    """Extract string-literal member values of NoteType and GemLevel classes."""
    wanted = ("NoteType", "GemLevel")
    result: dict[str, tuple[str, ...]] = {}
    for node in tree.body:
        if not isinstance(node, ast.ClassDef) or node.name not in wanted:
            continue
        if node.name in result:
            raise EnumCoverageError(f"models source: duplicate class {node.name}")
        values: list[str] = []
        for stmt in node.body:
            if not isinstance(stmt, ast.Assign):
                continue
            for target in stmt.targets:
                if not (isinstance(target, ast.Name) and target.id.isupper()):
                    continue
                if not (
                    isinstance(stmt.value, ast.Constant)
                    and isinstance(stmt.value.value, str)
                ):
                    raise EnumCoverageError(
                        f"models source: {node.name}.{target.id} must be a string literal"
                    )
                values.append(stmt.value.value)
        result[node.name] = tuple(values)
    missing = sorted(set(wanted) - set(result))
    if missing:
        raise EnumCoverageError(
            "models source: missing enum class(es): " + ", ".join(missing)
        )
    return result


def extract_model_enums(models_path: Path) -> DocumentedEnums:
    """Read enum values from the supplied models.py without importing it."""
    try:
        source = models_path.read_text(encoding="utf-8")
    except OSError as exc:
        raise EnumCoverageError(f"could not read models source {models_path}: {exc}") from exc
    try:
        tree = ast.parse(source)
    except SyntaxError as exc:
        raise EnumCoverageError(f"could not parse models source {models_path}: {exc}") from exc
    values = extract_enum_values_from_ast(tree)
    return DocumentedEnums(note_types=values["NoteType"], gem_levels=values["GemLevel"])


def _note_model_section(text: str) -> list[str]:
    lines = text.splitlines()
    start = None
    for index, line in enumerate(lines):
        if line.strip() == README_SECTION_HEADING:
            start = index
            break
    if start is None:
        raise EnumCoverageError("README: missing '## Note Model' section")
    end = len(lines)
    for index in range(start + 1, len(lines)):
        if lines[index].startswith("## "):
            end = index
            break
    return lines[start:end]


def parse_readme_enums(text: str) -> DocumentedEnums:
    """Parse documented NoteType table values and GemLevel chain values."""
    note_types: list[str] = []
    gem_levels: list[str] = []
    header_seen = False
    in_table = False
    in_chain_block = False
    for line in _note_model_section(text):
        stripped = line.strip()
        if stripped.startswith("```text"):
            in_chain_block = True
            continue
        if in_chain_block:
            if stripped == "```":
                in_chain_block = False
            elif GEM_CHAIN_ARROW in stripped:
                for part in stripped.split(GEM_CHAIN_ARROW):
                    value = part.strip().strip("`")
                    if not _IDENTIFIER.fullmatch(value):
                        raise EnumCoverageError(
                            f"README: malformed GemLevel chain value: {part.strip()!r}"
                        )
                    gem_levels.append(value)
            continue
        if stripped.startswith("|"):
            cells = stripped.split("|")
            header = cells[1].strip() if len(cells) > 1 else ""
            if not header_seen:
                if header == NOTE_TYPE_TABLE_HEADER:
                    header_seen = True
                    in_table = True
                continue
            if in_table:
                if set(header) <= {"-", ":", " "}:
                    continue
                match = _TABLE_ROW.match(stripped)
                if not match:
                    raise EnumCoverageError(
                        f"README: malformed Note Model table row (first cell must be "
                        f"backticked): {stripped}"
                    )
                note_types.append(match.group(1))
        else:
            in_table = False
    if not header_seen:
        raise EnumCoverageError("README: Note Model section has no 'Value' table")
    if not gem_levels:
        raise EnumCoverageError("README: Note Model section has no GemLevel arrow chain")
    return DocumentedEnums(note_types=tuple(note_types), gem_levels=tuple(gem_levels))


def validate_enum_coverage(
    model_values: DocumentedEnums,
    documented_values: DocumentedEnums,
) -> None:
    """Raise an actionable error when model and documented values diverge."""
    specs = (
        ("note_types", "NoteType", False),
        ("gem_levels", "GemLevel", True),
    )
    for field, enum_name, ordered in specs:
        model = getattr(model_values, field)
        documented = list(getattr(documented_values, field))
        seen: set[str] = set()
        for value in documented:
            if value in seen:
                raise EnumCoverageError(
                    f"{enum_name}: duplicate documented value {value!r} in README "
                    f"Note Model"
                )
            seen.add(value)
        errors: list[str] = []
        missing = [value for value in model if value not in seen]
        stale = [value for value in documented if value not in set(model)]
        if missing:
            errors.append(
                f"{enum_name}: add {', '.join(missing)} to the README Note Model section"
            )
        if stale:
            errors.append(
                f"{enum_name}: remove stale value(s) {', '.join(stale)} from the README "
                f"Note Model section"
            )
        if ordered and not missing and not stale and documented != list(model):
            errors.append(
                f"GemLevel: documented order {documented} does not match model order "
                f"{list(model)}; fix the arrow chain order"
            )
        if errors:
            raise EnumCoverageError("; ".join(errors))
