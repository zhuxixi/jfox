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
        root = (REPO_ROOT / "packages" / package / pointer).resolve()
        assert root.is_dir()
        for skill_dir in root.iterdir():
            if skill_dir.is_dir() and (skill_dir / "SKILL.md").is_file():
                rel = skill_dir.resolve().relative_to(REPO_ROOT / "packages").as_posix()
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
    _git(
        repo, "-c", "user.email=t@t", "-c", "user.name=t", "add",
        "docs/plugin-inventory.md",
    )
    _git(repo, "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-qm", "delete inventory")
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
