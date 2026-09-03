# Plugin Inventory and Enum Coverage Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Generate a structural `docs/plugin-inventory.md` from plugin manifests + skill directories, add a README-vs-`models.py` enum coverage check, and harden the Phase 3 gate with an untracked-generated-file check — all through the existing `generate_docs.py` entry point.

**Architecture:** Two new pure-function modules (`scripts/enum_coverage.py`, `scripts/plugin_inventory.py`) feed an extended `generate_all` orchestration in `scripts/generate_docs.py`. Enum values come from AST parsing `jfox/models.py` (no package import). The gate keeps `git diff --exit-code` and adds a targeted `git ls-files --others` check for the two generated outputs.

**Tech Stack:** Python ≥3.10 stdlib (`ast`, `json`, `argparse`, `pathlib`, `re`), PyYAML (existing), pytest, GitHub Actions YAML.

## Global Constraints

- Spec: `docs/superpowers/specs/2026-09-02-plugin-inventory-enum-checks-design.md` (issue #480).
- No new runtime dependencies; stdlib + existing PyYAML only.
- CLI command stays `uv run python scripts/generate_docs.py`; gate invocation unchanged.
- Generated inventory contains English structural facts only — never `SKILL.md` descriptions or trigger words.
- Enum source of truth is the AST of `jfox/models.py` string-literal members; never import the `jfox` package for the enum check.
- README is read-only for the checker (curated boundary).
- `generate_all` validates ALL sources before writing ANY output.
- Never push or open a PR from this plan — requires explicit user permission (AGENTS.md).
- All commands run in `$WT = /home/elling/git-repo/github/jfox/.pi/worktrees/issue-480-plugin-inventory-enum-checks`.
- Stage files explicitly with `git add <file>`; commit messages are conventional commits ending with `(#480)`.
- Existing CLI reference generation behavior and its tests must stay green (acceptance A10).
- New tests must not modify real repository files, the real README, packages/, or the user's global config.

---

## File Structure

| File | Responsibility |
|---|---|
| `scripts/enum_coverage.py` (create) | `DocumentedEnums`, AST enum extraction, README Note Model parser, coverage validation |
| `scripts/plugin_inventory.py` (create) | Manifest loading/resolution, skill discovery, `SkillEntry`, inventory rendering |
| `scripts/generate_docs.py` (modify) | `generate_all` orchestration, new CLI options, source-specific error handling |
| `docs/plugin-inventory.md` (create, generated) | Committed generated artifact |
| `.github/workflows/integration-test.yml` (modify) | `packages/**` filters (both triggers) + untracked-file gate check |
| `README.md` (modify) | One Agent Integrations link line |
| `tests/unit/test_enum_coverage.py` (create) | Unit tests for enum module |
| `tests/unit/test_plugin_inventory.py` (create) | Unit tests for inventory module |
| `tests/integration/test_plugin_inventory.py` (create) | Real-tree coverage, temp-git-repo gate proofs, determinism, static checks |
| `tests/integration/test_cli_reference_generation.py` (modify) | Redirect new default output to temp paths |

---

### Task 1: Enum coverage module (`scripts/enum_coverage.py`)

**Files:**

- Create: `scripts/enum_coverage.py`
- Test: `tests/unit/test_enum_coverage.py`

**Interfaces:**

- Consumes: nothing new (stdlib only).
- Produces: `DocumentedEnums`, `EnumCoverageError(ValueError)`, `extract_enum_values_from_ast(tree) -> dict[str, tuple[str, ...]]`, `extract_model_enums(path) -> DocumentedEnums`, `parse_readme_enums(text) -> DocumentedEnums`, `validate_enum_coverage(model_values, documented_values) -> None`. Later tasks import these names verbatim.

**Acceptance IDs:** A5, A6, A7 (unit halves).

- [ ] **Step 1: Write failing unit tests**

Create `tests/unit/test_enum_coverage.py`:

```python
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run in `$WT`:

```bash
uv run pytest tests/unit/test_enum_coverage.py -q
```

Expected: collection error / FAIL — `ModuleNotFoundError: No module named 'scripts.enum_coverage'`.

- [ ] **Step 3: Implement `scripts/enum_coverage.py`**

```python
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
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
uv run pytest tests/unit/test_enum_coverage.py -q
```

Expected: 13 passed.

- [ ] **Step 5: Commit**

```bash
git add scripts/enum_coverage.py tests/unit/test_enum_coverage.py
git commit -m "feat(docs): add enum coverage checker module (#480)"
```

---

### Task 2: Plugin inventory module (`scripts/plugin_inventory.py`)

**Files:**

- Create: `scripts/plugin_inventory.py`
- Test: `tests/unit/test_plugin_inventory.py`

**Interfaces:**

- Consumes: `GENERATED_MARKER` imported from `scripts.generate_docs` (no cycle — `generate_docs` does not import this module at top level).
- Produces: `PLUGIN_PACKAGES`, `PluginInventoryError(ValueError)`, `SkillEntry(package, name, relative_source)`, `load_plugin_manifests(packages_root)`, `resolve_manifest_skill_roots(manifest_data, package_root)`, `discover_skill_paths(skill_root)`, `extract_skill_inventory(packages_root)`, `render_inventory(entries)`. Task 3 imports these verbatim.

**Acceptance IDs:** A1, A3 (unit halves).

- [ ] **Step 1: Write failing unit tests**

Create `tests/unit/test_plugin_inventory.py`:

```python
from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts.plugin_inventory import (
    PLUGIN_PACKAGES,
    PluginInventoryError,
    discover_skill_paths,
    extract_skill_inventory,
    load_plugin_manifests,
    render_inventory,
    resolve_manifest_skill_roots,
)


def _make_package(root: Path, package: str, skills: dict[str, bool], pointer: str | None):
    skills_dir = root / package / "skills"
    for name, has_skill in skills.items():
        skill_dir = skills_dir / name
        skill_dir.mkdir(parents=True)
        if has_skill:
            (skill_dir / "SKILL.md").write_text("---\nname: x\n---\n", encoding="utf-8")
    if package == "cc-plugin":
        manifest_dir = root / package / ".claude-plugin"
        manifest_dir.mkdir(parents=True, exist_ok=True)
        manifest_path = manifest_dir / "plugin.json"
    else:
        manifest_path = root / package / "kimi.plugin.json"
    manifest: dict = {"name": package}
    if pointer is not None:
        manifest["skills"] = pointer
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")


def _make_tree(root: Path):
    _make_package(root, "cc-plugin", {"alpha": True, "beta": True}, pointer=None)
    _make_package(
        root, "kimi-plugin", {"jfox-alpha": True, "not-a-skill": False}, pointer="./skills/"
    )


def test_resolve_manifest_skill_roots():
    pkg = Path("/tmp/pkg")

    assert resolve_manifest_skill_roots({}, pkg) == pkg / "skills"
    assert resolve_manifest_skill_roots({"skills": "./skills/"}, pkg) == pkg / "skills"
    with pytest.raises(PluginInventoryError, match="non-empty relative string"):
        resolve_manifest_skill_roots({"skills": ""}, pkg)
    with pytest.raises(PluginInventoryError, match="non-empty relative string"):
        resolve_manifest_skill_roots({"skills": ["./skills/"]}, pkg)
    with pytest.raises(PluginInventoryError, match="escapes the package root"):
        resolve_manifest_skill_roots({"skills": "../../elsewhere"}, pkg)


def test_load_plugin_manifests(tmp_path: Path):
    _make_tree(tmp_path)

    manifests = load_plugin_manifests(tmp_path)

    assert set(manifests) == set(PLUGIN_PACKAGES)
    assert manifests["kimi-plugin"]["skills"] == "./skills/"

    broken = tmp_path / "kimi-plugin" / "kimi.plugin.json"
    broken.write_text("{not json", encoding="utf-8")
    with pytest.raises(PluginInventoryError, match="invalid JSON"):
        load_plugin_manifests(tmp_path)

    broken.write_text("[]", encoding="utf-8")
    with pytest.raises(PluginInventoryError, match="must be a JSON object"):
        load_plugin_manifests(tmp_path)

    broken.unlink()
    with pytest.raises(PluginInventoryError, match="could not read"):
        load_plugin_manifests(tmp_path)


def test_discover_skill_paths(tmp_path: Path):
    root = tmp_path / "skills"
    (root / "alpha").mkdir(parents=True)
    (root / "alpha" / "SKILL.md").write_text("x", encoding="utf-8")
    (root / "ignored").mkdir()
    (root / "zz-last").mkdir()
    (root / "zz-last" / "SKILL.md").write_text("x", encoding="utf-8")

    assert discover_skill_paths(root) == ("alpha", "zz-last")

    with pytest.raises(PluginInventoryError, match="does not exist"):
        discover_skill_paths(tmp_path / "missing")


def test_extract_skill_inventory_ignores_non_skill_dirs(tmp_path: Path):
    _make_tree(tmp_path)

    entries = extract_skill_inventory(tmp_path)

    assert [(e.package, e.name) for e in entries] == [
        ("cc-plugin", "alpha"),
        ("cc-plugin", "beta"),
        ("kimi-plugin", "jfox-alpha"),
    ]
    assert entries[0].relative_source == "cc-plugin/skills/alpha/"


def test_inventory_includes_new_skill_directory(tmp_path: Path):
    _make_tree(tmp_path)
    before = render_inventory(extract_skill_inventory(tmp_path))

    new_skill = tmp_path / "cc-plugin" / "skills" / "new-skill"
    new_skill.mkdir()
    (new_skill / "SKILL.md").write_text("x", encoding="utf-8")
    after = render_inventory(extract_skill_inventory(tmp_path))

    assert "`new-skill`" in after
    assert "`new-skill`" not in before
    assert after != before


def test_inventory_excludes_removed_skill_directory(tmp_path: Path):
    _make_tree(tmp_path)
    before = render_inventory(extract_skill_inventory(tmp_path))

    removed = tmp_path / "cc-plugin" / "skills" / "alpha"
    for child in removed.iterdir():
        child.unlink()
    removed.rmdir()
    after = render_inventory(extract_skill_inventory(tmp_path))

    assert "`alpha`" not in after
    assert "`alpha`" in before


def test_render_inventory_structure_and_order(tmp_path: Path):
    _make_tree(tmp_path)

    rendered = render_inventory(extract_skill_inventory(tmp_path))
    again = render_inventory(extract_skill_inventory(tmp_path))

    assert rendered == again
    assert rendered.startswith("<!--\nThis file is generated by scripts/generate_docs.py.")
    assert "# JFox Plugin Skill Inventory" in rendered
    assert rendered.index("## `cc-plugin`") < rendered.index("## `kimi-plugin`")
    assert "| Skill | Source |" in rendered
    assert "| `jfox-alpha` | `kimi-plugin/skills/jfox-alpha/` |" in rendered
    assert "not-a-skill" not in rendered
    assert "\r" not in rendered and rendered.endswith("\n")


def test_render_inventory_omits_package_without_skills(tmp_path: Path):
    _make_package(tmp_path, "cc-plugin", {"alpha": True}, pointer=None)
    _make_package(tmp_path, "kimi-plugin", {}, pointer="./skills/")

    rendered = render_inventory(extract_skill_inventory(tmp_path))

    assert "## `cc-plugin`" in rendered
    assert "kimi-plugin" not in rendered.replace("This inventory", "")
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
uv run pytest tests/unit/test_plugin_inventory.py -q
```

Expected: FAIL — `ModuleNotFoundError: No module named 'scripts.plugin_inventory'`.

- [ ] **Step 3: Implement `scripts/plugin_inventory.py`**

```python
"""Pure helpers resolving plugin manifests and rendering the skill inventory."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Sequence

from scripts.generate_docs import GENERATED_MARKER

PLUGIN_PACKAGES: tuple[str, ...] = ("cc-plugin", "kimi-plugin")


class PluginInventoryError(ValueError):
    """Plugin manifests or skill directories violate the inventory contract."""


@dataclass(frozen=True)
class SkillEntry:
    package: str
    name: str
    relative_source: str


def _manifest_path(packages_root: Path, package: str) -> Path:
    if package == "cc-plugin":
        return packages_root / package / ".claude-plugin" / "plugin.json"
    return packages_root / package / "kimi.plugin.json"


def load_plugin_manifests(packages_root: Path) -> dict[str, dict]:
    """Load and validate the known plugin manifests as JSON objects."""
    manifests: dict[str, dict] = {}
    for package in PLUGIN_PACKAGES:
        path = _manifest_path(packages_root, package)
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except OSError as exc:
            raise PluginInventoryError(
                f"could not read plugin manifest {path}: {exc}"
            ) from exc
        except json.JSONDecodeError as exc:
            raise PluginInventoryError(
                f"invalid JSON in plugin manifest {path}: {exc}"
            ) from exc
        if not isinstance(data, dict):
            raise PluginInventoryError(
                f"plugin manifest must be a JSON object: {path}"
            )
        manifests[package] = data
    return manifests


def resolve_manifest_skill_roots(manifest_data: dict, package_root: Path) -> Path:
    """Resolve the manifest skill root; absent means the default skills/ root."""
    raw = manifest_data.get("skills")
    if raw is None:
        return package_root / "skills"
    if not isinstance(raw, str) or not raw.strip():
        raise PluginInventoryError(
            f"manifest 'skills' must be a non-empty relative string "
            f"(package root: {package_root})"
        )
    resolved = (package_root / raw).resolve()
    package_resolved = package_root.resolve()
    if resolved != package_resolved and package_resolved not in resolved.parents:
        raise PluginInventoryError(
            f"manifest 'skills' escapes the package root (package root: {package_root})"
        )
    return resolved


def discover_skill_paths(skill_root: Path) -> tuple[str, ...]:
    """Return sorted names of immediate child dirs containing SKILL.md."""
    if not skill_root.is_dir():
        raise PluginInventoryError(f"skill root does not exist: {skill_root}")
    names = [
        child.name
        for child in skill_root.iterdir()
        if child.is_dir() and (child / "SKILL.md").is_file()
    ]
    return tuple(sorted(names))


def extract_skill_inventory(packages_root: Path) -> tuple[SkillEntry, ...]:
    """Resolve manifests and discover skill directories across packages."""
    manifests = load_plugin_manifests(packages_root)
    root_resolved = packages_root.resolve()
    entries: list[SkillEntry] = []
    for package in PLUGIN_PACKAGES:
        skill_root = resolve_manifest_skill_roots(
            manifests[package], packages_root / package
        )
        try:
            rel_root = skill_root.resolve().relative_to(root_resolved).as_posix()
        except ValueError as exc:
            raise PluginInventoryError(
                f"resolved skill root outside packages root: {skill_root}"
            ) from exc
        for name in discover_skill_paths(skill_root):
            entries.append(
                SkillEntry(
                    package=package,
                    name=name,
                    relative_source=f"{rel_root}/{name}/",
                )
            )
    return tuple(entries)


def render_inventory(entries: Sequence[SkillEntry]) -> str:
    """Render deterministic English structural inventory Markdown."""
    lines = [
        GENERATED_MARKER,
        "",
        "# JFox Plugin Skill Inventory",
        "",
        "This inventory is generated from plugin manifests and discoverable skill directories.",
    ]
    for package in PLUGIN_PACKAGES:
        package_entries = sorted(
            (entry for entry in entries if entry.package == package),
            key=lambda entry: entry.name,
        )
        if not package_entries:
            continue
        rel_root = package_entries[0].relative_source
        rel_root = rel_root[: -len(package_entries[0].name) - 1]
        lines.extend(
            [
                "",
                f"## `{package}`",
                "",
                f"Source root: `{rel_root}/`",
                "",
                "| Skill | Source |",
                "|---|---|",
            ]
        )
        for entry in package_entries:
            lines.append(f"| `{entry.name}` | `{entry.relative_source}` |")
    return "\n".join(lines) + "\n"
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
uv run pytest tests/unit/test_plugin_inventory.py -q
```

Expected: 8 passed.

- [ ] **Step 5: Commit**

```bash
git add scripts/plugin_inventory.py tests/unit/test_plugin_inventory.py
git commit -m "feat(docs): add plugin inventory module (#480)"
```

---

### Task 3: Orchestration in `generate_docs.py` + regenerate outputs + update existing tests

**Files:**

- Modify: `scripts/generate_docs.py`
- Create: `docs/plugin-inventory.md` (generated, committed)
- Modify: `tests/integration/test_cli_reference_generation.py`

**Interfaces:**

- Consumes: Task 1 `enum_coverage` names; Task 2 `plugin_inventory` names; existing `extract_commands`/`load_descriptions`/`validate_descriptions`/`render_reference`/`write_reference`.
- Produces: `generate_all(cli_output, descriptions, inventory_output, readme_path, models_path, packages_root)`; CLI options `--inventory-output`, `--readme`, `--models`, `--packages-root`. Task 5's subprocess tests call these flags.

**Acceptance IDs:** A8 (integration half), A9 (determinism setup), A10.

- [ ] **Step 1: Add `generate_all` and source-specific error handling**

In `scripts/generate_docs.py`:

First, add top-level imports after the existing ones:

```python
from scripts.enum_coverage import (
    EnumCoverageError,
    extract_model_enums,
    parse_readme_enums,
    validate_enum_coverage,
)
from scripts.plugin_inventory import (
    PluginInventoryError,
    extract_skill_inventory,
    render_inventory,
)
```

Then, add `generate_all` after `generate_reference`:

```python
def generate_all(
    cli_output: Path,
    descriptions: Path,
    inventory_output: Path,
    readme_path: Path,
    models_path: Path,
    packages_root: Path,
) -> None:
    """Validate every source, then write both generated documents."""
    _ensure_isolated_config_environment()

    inventory_entries = extract_skill_inventory(packages_root)
    inventory_markdown = render_inventory(inventory_entries)
    model_values = extract_model_enums(models_path)
    documented_values = parse_readme_enums(readme_path.read_text(encoding="utf-8"))
    validate_enum_coverage(model_values, documented_values)

    from typer.main import get_command

    from jfox.cli import app

    commands = extract_commands(get_command(app), root_name="jfox")
    catalog = load_descriptions(descriptions)
    validate_descriptions((command.path for command in commands), catalog)
    cli_markdown = render_reference(commands, catalog)

    write_reference(cli_output, cli_markdown)
    write_reference(inventory_output, inventory_markdown)
```

Finally, replace `main()` with the extended version (keep `generate_reference` intact for existing callers):

```python
def main() -> int:
    parser = argparse.ArgumentParser(description="Generate the JFox English docs")
    parser.add_argument("--output", type=Path, default=Path("docs/cli-reference.md"))
    parser.add_argument("--descriptions", type=Path, default=Path("docs/cli-descriptions.yaml"))
    parser.add_argument(
        "--inventory-output", type=Path, default=Path("docs/plugin-inventory.md")
    )
    parser.add_argument("--readme", type=Path, default=Path("README.md"))
    parser.add_argument("--models", type=Path, default=Path("jfox/models.py"))
    parser.add_argument("--packages-root", type=Path, default=Path("packages"))
    args = parser.parse_args()
    root = _repository_root()

    def resolve(value: Path) -> Path:
        return value if value.is_absolute() else root / value

    try:
        generate_all(
            cli_output=resolve(args.output),
            descriptions=resolve(args.descriptions),
            inventory_output=resolve(args.inventory_output),
            readme_path=resolve(args.readme),
            models_path=resolve(args.models),
            packages_root=resolve(args.packages_root),
        )
    except EnumCoverageError as exc:
        parser.error(str(exc))
    except PluginInventoryError as exc:
        parser.error(str(exc))
    except OSError as exc:
        parser.error(str(exc))
    except ValueError as exc:
        parser.error(f"{exc}; update docs/cli-descriptions.yaml and rerun the generator")
    except ImportError as exc:
        parser.error(str(exc))
    print(f"Generated {resolve(args.output)}")
    print(f"Generated {resolve(args.inventory_output)}")
    return 0
```

- [ ] **Step 2: Regenerate the committed outputs**

```bash
uv run python scripts/generate_docs.py
git status --short
```

Expected: `docs/plugin-inventory.md` appears as a new untracked file; `docs/cli-reference.md` unchanged (diff empty). Inspect the new file: marker first, both package sections, 9 + 11 rows, no descriptions.

- [ ] **Step 3: Update the existing CLI-reference subprocess helper**

In `tests/integration/test_cli_reference_generation.py`, extend `_run_generator` so the new default output never lands in the repo — add an `--inventory-output` pointing into `tmp_path`:

```python
def _run_generator(output: Path, tmp_path: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            sys.executable,
            str(GENERATOR),
            "--output",
            str(output),
            "--descriptions",
            str(DESCRIPTIONS),
            "--inventory-output",
            str(tmp_path / "plugin-inventory.md"),
        ],
        cwd=REPO_ROOT,
        env=_isolated_env(tmp_path),
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )
```

- [ ] **Step 4: Run the existing suite**

```bash
uv run pytest tests/integration/test_cli_reference_generation.py tests/unit/test_generate_docs.py -q
```

Expected: all pass (the generator now also validates enums/inventory against the real repo, which is currently aligned).

- [ ] **Step 5: Commit**

```bash
git add scripts/generate_docs.py docs/plugin-inventory.md tests/integration/test_cli_reference_generation.py
git commit -m "feat(docs): generate plugin inventory and check enum coverage (#480)"
```

---

### Task 4: Gate extension, path filters, README link

**Files:**

- Modify: `.github/workflows/integration-test.yml`
- Modify: `README.md`

**Interfaces:**

- Consumes: the gate contract from spec §4.5 and the README line from spec §4.6 (verbatim below).
- Produces: the workflow/gate state that Task 5's static tests assert against.

**Acceptance IDs:** A4 (gate logic), A11, A12 (setup), U1/U2 (post-push).

- [ ] **Step 1: Add `packages/**` to both path filters**

In `.github/workflows/integration-test.yml`, add `- 'packages/**'` after the `- 'docs/cli-descriptions.yaml'` line in BOTH the `push:` block (~line 12) and the `pull_request:` block (~line 23).

- [ ] **Step 2: Replace the gate step comparison block**

Replace the `Check generated docs are up to date` step body with the spec §4.5 block verbatim:

```yaml
    - name: Check generated docs are up to date
      run: |
        uv run python scripts/generate_docs.py
        untracked_generated="$(git ls-files --others --exclude-standard -- \
          docs/cli-reference.md docs/plugin-inventory.md)"
        if ! git diff --exit-code; then
          tracked_drift=1
        else
          tracked_drift=0
        fi
        if [ "$tracked_drift" -ne 0 ] || [ -n "$untracked_generated" ]; then
          echo "::error::Generated documentation is stale or untracked. Regenerate locally with:"
          echo "::error::  uv run python scripts/generate_docs.py"
          echo "--- Tracked changes ---"
          git diff --name-only
          if [ -n "$untracked_generated" ]; then
            echo "--- Untracked generated files ---"
            printf '%s\n' "$untracked_generated"
          fi
          exit 1
        fi
```

- [ ] **Step 3: Verify YAML syntax**

```bash
uv run python -c "import yaml; yaml.safe_load(open('.github/workflows/integration-test.yml')); print('YAML syntax OK')"
```

Expected: `YAML syntax OK`.

- [ ] **Step 4: Add the README link line**

In `README.md`, under `## Agent Integrations`, immediately after the paragraph ending with `...can evolve independently from the core command-line application.` (before the next level-2 heading), add:

```markdown

For the current per-skill directory inventory, see the [generated plugin skill inventory](docs/plugin-inventory.md).
```

- [ ] **Step 5: Verify README lint**

```bash
npx --yes markdownlint-cli2@0.23.2 README.md
```

Expected: exit 0.

- [ ] **Step 6: Commit**

```bash
git add .github/workflows/integration-test.yml README.md
git commit -m "ci: harden docs gate and cover packages paths (#480)"
```

---

### Task 5: Integration tests (`tests/integration/test_plugin_inventory.py`)

**Files:**

- Create: `tests/integration/test_plugin_inventory.py`

**Interfaces:**

- Consumes: `generate_all` via subprocess CLI flags; real repo files read-only; temp git repos for gate proofs.
- Produces: the automated evidence for A2/A3/E2E/A4/A8/A9/A11/A12.

**Acceptance IDs:** A2, A3 (integration half), A4, A8, A9, A11, A12.

- [ ] **Step 1: Write the integration tests**

Create `tests/integration/test_plugin_inventory.py`:

```python
from __future__ import annotations

import hashlib
import os
import subprocess
import sys
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
GENERATOR = REPO_ROOT / "scripts" / "generate_docs.py"
WORKFLOW = REPO_ROOT / ".github" / "workflows" / "integration-test.yml"
README = REPO_ROOT / "README.md"
INVENTORY = REPO_ROOT / "docs" / "plugin-inventory.md"


def _env(tmp_path: Path) -> dict[str, str]:
    home = tmp_path / "home"
    home.mkdir(parents=True, exist_ok=True)
    env = os.environ.copy()
    env.update(
        {
            "HOME": str(home),
            "USERPROFILE": str(home),
            "ZK_CONFIG_PATH": str(home / "zk_config.json"),
            "ZK_KB_ROOT": str(home / ".zettelkasten"),
            "PYTHONUTF8": "1",
        }
    )
    return env


def _run(tmp_path: Path, *extra: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(GENERATOR), *extra],
        cwd=REPO_ROOT,
        env=_env(tmp_path),
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )


def test_real_inventory_matches_skill_directories():
    """The generated inventory equals an independent glob of SKILL.md dirs."""
    discovered = set()
    for package, marker in (
        ("cc-plugin", "packages/cc-plugin/.claude-plugin/plugin.json"),
        ("kimi-plugin", "packages/kimi-plugin/kimi.plugin.json"),
    ):
        manifest = yaml.safe_load((REPO_ROOT / marker).read_text(encoding="utf-8"))
        pointer = manifest.get("skills", "./skills/")
        root = (REPO_ROOT / package / pointer).resolve()
        assert root.is_dir()
        for skill_dir in root.iterdir():
            if skill_dir.is_dir() and (skill_dir / "SKILL.md").is_file():
                rel = skill_dir.resolve().relative_to(REPO_ROOT).as_posix()
                discovered.add((package, skill_dir.name, rel + "/"))
    counts = {pkg: sum(1 for e in discovered if e[0] == pkg) for pkg in discovered}
    print(f"diagnostic counts: {counts}")

    content = INVENTORY.read_text(encoding="utf-8")
    for _package, name, rel in discovered:
        assert f"| `{name}` | `{rel}` |" in content
    rows = [line for line in content.splitlines() if line.startswith("| `")]
    assert len(rows) == len(discovered)


def test_current_enum_coverage(tmp_path: Path):
    """Current models.py and README pass the full generator end to end."""
    result = _run(
        tmp_path,
        "--output", str(tmp_path / "cli.md"),
        "--inventory-output", str(tmp_path / "inv.md"),
    )
    assert result.returncode == 0, result.stderr


def test_full_generation_is_deterministic(tmp_path: Path):
    first = tmp_path / "a"
    second = tmp_path / "b"
    for run, out in (("a", first), ("b", second)):
        result = _run(
            tmp_path / run,
            "--output", str(out / "cli.md"),
            "--inventory-output", str(out / "inv.md"),
        )
        assert result.returncode == 0, result.stderr
    assert (first / "cli.md").read_bytes() == (second / "cli.md").read_bytes()
    assert (first / "inv.md").read_bytes() == (second / "inv.md").read_bytes()
    assert hashlib.sha256((first / "inv.md").read_bytes()).hexdigest()


def _git(repo: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", "-C", str(repo), *args],
        capture_output=True,
        text=True,
        check=False,
    )


def _make_gate_repo(tmp_path: Path) -> Path:
    """Build a minimal repo whose generated files are tracked and fresh."""
    repo = tmp_path / "repo"
    (repo / "docs").mkdir(parents=True)
    (repo / "docs" / "cli-reference.md").write_text("cli\n", encoding="utf-8")
    (repo / "docs" / "plugin-inventory.md").write_text("inv\n", encoding="utf-8")
    _git(repo, "init", "-q")
    _git(
        repo, "-c", "user.email=t@t", "-c", "user.name=t", "add",
        "docs/cli-reference.md", "docs/plugin-inventory.md",
    )
    _git(repo, "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-qm", "base")
    return repo


def test_stale_inventory_diff_is_nonzero(tmp_path: Path):
    """A tracked-but-stale generated file is caught by git diff --exit-code."""
    repo = _make_gate_repo(tmp_path)
    (repo / "docs" / "plugin-inventory.md").write_text("inv-changed\n", encoding="utf-8")
    result = _git(repo, "diff", "--exit-code")
    assert result.returncode != 0


def test_deleted_inventory_is_detected_as_untracked(tmp_path: Path):
    """Deleting a committed generated file and recreating it leaves an untracked
    file that the gate's git ls-files --others check catches."""
    repo = _make_gate_repo(tmp_path)
    (repo / "docs" / "plugin-inventory.md").unlink()
    assert _git(repo, "diff", "--exit-code").returncode != 0  # deletion is tracked drift
    (repo / "docs" / "plugin-inventory.md").write_text("inv-regenerated\n", encoding="utf-8")
    result = _git(
        repo, "ls-files", "--others", "--exclude-standard",
        "--", "docs/cli-reference.md", "docs/plugin-inventory.md",
    )
    assert result.stdout.strip() == "docs/plugin-inventory.md"
    assert result.stdout  # non-empty => the gate would fail


def test_workflow_paths_include_packages():
    data = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
    triggers = data.get(True) or data.get("on")  # PyYAML parses bare `on` as True
    for event in ("push", "pull_request"):
        assert "packages/**" in triggers[event]["paths"], event


def test_readme_links_inventory():
    text = README.read_text(encoding="utf-8")
    assert "[generated plugin skill inventory](docs/plugin-inventory.md)" in text
    assert "## `cc-plugin`" not in text  # curated README never copies inventory rows
```

Note: `test_workflow_paths_include_packages` asserts both trigger blocks; if the assertion fails because `on` resolved differently, inspect `data.keys()` and adjust the key lookup to the actual parsed key (the value is the same dict).

- [ ] **Step 2: Run the integration tests**

```bash
uv run pytest tests/integration/test_plugin_inventory.py -q
```

Expected: 7 passed.

- [ ] **Step 3: Commit**

```bash
git add tests/integration/test_plugin_inventory.py
git commit -m "test(docs): integration coverage for inventory and gate checks (#480)"
```

---

### Task 6: Final local verification and acceptance reconciliation

**Files:** none (verification only).

**Interfaces:**

- Consumes: all commits from Tasks 1-5.
- Produces: verification record for the PR body (written at push time, outside this plan).

**Acceptance IDs:** A1-A12 local halves; U1/U2 remain user-tested post-push.

- [ ] **Step 1: Full targeted test pass**

```bash
uv run pytest tests/unit/test_enum_coverage.py tests/unit/test_plugin_inventory.py tests/integration/test_plugin_inventory.py tests/integration/test_cli_reference_generation.py tests/unit/test_generate_docs.py -q
```

Expected: all pass, output pristine.

- [ ] **Step 2: Lint and format checks (Python changed this time)**

```bash
uv run ruff check scripts/ tests/ jfox/
uv run black --check scripts/enum_coverage.py scripts/plugin_inventory.py scripts/generate_docs.py tests/unit/test_enum_coverage.py tests/unit/test_plugin_inventory.py tests/integration/test_plugin_inventory.py tests/integration/test_cli_reference_generation.py
npx --yes markdownlint-cli2@0.23.2 "**/*.md" "#node_modules" "#.venv"
```

Expected: ruff clean, black clean, markdownlint 0 findings. Fix and re-run if not (note: ruff/black scope for scripts is new — if the repo config excludes `scripts/`, keep the explicit file list above).

- [ ] **Step 3: Whole-tree gate simulation on the final branch**

```bash
uv run python scripts/generate_docs.py
untracked="$(git ls-files --others --exclude-standard -- docs/cli-reference.md docs/plugin-inventory.md)"
git diff --exit-code && [ -z "$untracked" ] && echo "GATE GREEN"
```

Expected: `GATE GREEN` (no tracked drift, no untracked generated files).

- [ ] **Step 4: Acceptance reconciliation**

Verify each spec §5 ID: A1 (Task 1/2 unit tests), A2/A3/A4 (Task 5), A5/A6/A7 (Task 1), A8 (Tasks 3/5), A9 (Task 5), A10 (Task 3 Step 4), A11/A12 (Task 4 + Task 5). U1 (package-only manifest formatting push on a temp branch) and U2 (`workflow_dispatch` fast) remain user-tested. Record any pending CI-side evidence honestly.

- [ ] **Step 5: Stop**

Report completion and stop. Push/PR is issue-driven step 9 and requires explicit user permission.
