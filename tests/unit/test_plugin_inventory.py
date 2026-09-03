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
    skills_dir.mkdir(parents=True, exist_ok=True)
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


def test_resolve_manifest_skill_roots(tmp_path: Path):
    # tmp_path is guaranteed resolved by pytest, keeping both sides of the
    # comparison normalization-stable on every platform (a literal "/tmp/pkg"
    # resolves to "D:/tmp/pkg" on Windows and breaks the assertion).
    pkg = tmp_path / "pkg"
    pkg.mkdir()

    assert resolve_manifest_skill_roots({}, pkg) == pkg / "skills"
    assert resolve_manifest_skill_roots({"skills": "./skills/"}, pkg) == (pkg / "skills").resolve()
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
    assert "Source root: `cc-plugin/skills/`" in rendered
    assert "//" not in rendered
    assert "not-a-skill" not in rendered
    assert "\r" not in rendered and rendered.endswith("\n")


def test_render_inventory_omits_package_without_skills(tmp_path: Path):
    _make_package(tmp_path, "cc-plugin", {"alpha": True}, pointer=None)
    _make_package(tmp_path, "kimi-plugin", {}, pointer="./skills/")

    rendered = render_inventory(extract_skill_inventory(tmp_path))

    assert "## `cc-plugin`" in rendered
    assert "kimi-plugin" not in rendered.replace("This inventory", "")
