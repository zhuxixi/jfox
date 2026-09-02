"""Pure helpers resolving plugin manifests and rendering the skill inventory."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
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
