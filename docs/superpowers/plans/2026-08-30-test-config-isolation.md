# Test Config Isolation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Prevent pytest and its CLI child processes from reading or writing the user's real `~/.zk_config.json`, while preserving the existing default path for normal users.

**Architecture:** Add the process-start configuration override `ZK_CONFIG_PATH` beside the existing `ZK_KB_ROOT` override. `jfox.global_config.DEFAULT_CONFIG_PATH` reads the override once during module import, while an explicit `GlobalConfigManager(config_path=...)` remains authoritative. The pytest bootstrap sets a temporary config path before importing any JFox helpers, and subprocess regression tests verify the complete CLI boundary.

**Tech Stack:** Python 3.10+, `pathlib`, `os.environ`, `subprocess`, pytest, Typer CLI.

## Global Constraints

- Keep the default behavior as `Path.home() / ".zk_config.json"` when `ZK_CONFIG_PATH` is unset or blank.
- Preserve the explicit `GlobalConfigManager(config_path=...)` dependency-injection path.
- Set the test config path before importing modules that load `jfox.global_config`.
- Ensure `ZKCLI` child processes inherit the isolated config path through the existing copied environment.
- Do not read, snapshot, modify, or clean the user's real `~/.zk_config.json` in tests.
- Keep the existing fixture `try/finally` and session cleanup as defensive cleanup, not as the primary isolation mechanism.
- Do not change CLI KB selection messages, daemon concurrency behavior, or user configuration migration behavior.
- Use only the existing Python and pytest dependencies; do not add packages.
- Work only from `/home/elling/git-repo/github/jfox/.pi/worktrees/issue-460-test-config-isolation`; do not modify the main checkout.

---

## File Map

- Modify `jfox/global_config.py`: resolve `DEFAULT_CONFIG_PATH` from `ZK_CONFIG_PATH` with the current HOME-based fallback.
- Modify `tests/conftest.py`: set `ZK_CONFIG_PATH` to a per-session path under `_TEST_ROOT` before importing JFox test helpers.
- Modify `tests/unit/test_global_config.py`: add subprocess regression coverage for the environment override, fallback behavior, and the pytest bootstrap path.
- Keep `docs/superpowers/specs/2026-08-30-test-config-isolation-design.md` as the approved design record; do not add unrelated documentation or production refactors.

## Interfaces

- Existing public constructor remains unchanged: `GlobalConfigManager(config_path: Optional[Path] = None)`.
- Existing module constant remains available: `DEFAULT_CONFIG_PATH: Path`.
- New process-level contract: non-blank `ZK_CONFIG_PATH` selects the default global config file for all default-constructed managers in that process.

### Task 1: Add failing regression tests

**Files:**

- Modify: `tests/unit/test_global_config.py` near the imports and `TestGlobalConfigManager`

**Interfaces:**

- Consumes: current `DEFAULT_CONFIG_PATH`, `DEFAULT_KB_PATH`, and `GlobalConfigManager` imports.
- Produces: tests that fail under the current hard-coded `Path.home()` implementation and prove the CLI subprocess boundary.

- [ ] **Step 1: Add the required test imports.**

Add these imports to the existing import block in `tests/unit/test_global_config.py`:

```python
import os
import subprocess
import sys
```

Keep the existing `pytest`, `json`, `datetime`, `Path`, and `patch` imports intact.

- [ ] **Step 2: Add a test for the pytest bootstrap config path.**

Add this test method to `TestGlobalConfigManager`:

```python
    def test_pytest_bootstrap_uses_isolated_config_path(self):
        """pytest bootstrap must point the default config path into its temp root."""
        configured_path = os.environ.get("ZK_CONFIG_PATH")

        assert configured_path
        assert DEFAULT_CONFIG_PATH == Path(configured_path)
        assert DEFAULT_CONFIG_PATH.name == "zk_config.json"
        assert DEFAULT_CONFIG_PATH.parent.name.startswith("zk_test_root_")
```

This test must fail before the conftest change because `ZK_CONFIG_PATH` is not currently set.

- [ ] **Step 3: Add a subprocess helper and environment override test.**

Add this helper immediately before `TestGlobalConfigManager`:

```python
def _probe_default_config_path(env):
    """Return DEFAULT_CONFIG_PATH from a fresh Python interpreter."""
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "from jfox.global_config import DEFAULT_CONFIG_PATH; "
            "print(DEFAULT_CONFIG_PATH)",
        ],
        cwd=Path(__file__).resolve().parents[2],
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )
    assert result.returncode == 0, result.stderr
    return Path(result.stdout.strip())
```

Add this test method to `TestGlobalConfigManager`:

```python
    def test_default_config_path_uses_environment_override_in_child_process(self, tmp_path):
        """A CLI-like child process must resolve ZK_CONFIG_PATH instead of HOME."""
        home = tmp_path / "home"
        custom_config = tmp_path / "config" / "isolated.json"
        env = os.environ.copy()
        env.update(
            {
                "HOME": str(home),
                "USERPROFILE": str(home),
                "ZK_CONFIG_PATH": str(custom_config),
            }
        )

        assert _probe_default_config_path(env) == custom_config
```

This test must fail before the production change because the child process currently resolves `home/.zk_config.json`.

- [ ] **Step 4: Add the default fallback test.**

Add this test method to `TestGlobalConfigManager`:

```python
    def test_default_config_path_falls_back_to_home_when_override_is_blank(self, tmp_path):
        """A blank override must preserve the existing HOME-based default path."""
        home = tmp_path / "home"
        env = os.environ.copy()
        env.update(
            {
                "HOME": str(home),
                "USERPROFILE": str(home),
                "ZK_CONFIG_PATH": "   ",
            }
        )

        assert _probe_default_config_path(env) == home / ".zk_config.json"
```

This test documents the backward-compatible fallback and should pass once the override is implemented.

- [ ] **Step 5: Add the end-to-end CLI write-location test.**

Add this test method to `TestGlobalConfigManager`:

```python
    def test_cli_child_writes_only_to_environment_config_path(self, tmp_path):
        """CLI KB registration must not create a config file under the child HOME."""
        home = tmp_path / "home"
        kb_root = tmp_path / "kb-root"
        custom_config = tmp_path / "config" / "isolated.json"
        kb_path = kb_root / "isolated"
        kb_root.mkdir(parents=True)
        env = os.environ.copy()
        env.update(
            {
                "HOME": str(home),
                "USERPROFILE": str(home),
                "ZK_KB_ROOT": str(kb_root),
                "ZK_CONFIG_PATH": str(custom_config),
                "PYTHONUTF8": "1",
            }
        )

        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "jfox",
                "init",
                "--name",
                "isolated",
                "--path",
                str(kb_path),
                "--no-default",
                "--json",
            ],
            cwd=Path(__file__).resolve().parents[2],
            env=env,
            capture_output=True,
            text=True,
            encoding="utf-8",
            check=False,
        )

        assert result.returncode == 0, result.stderr
        assert custom_config.exists()
        assert not (home / ".zk_config.json").exists()
        assert '"isolated"' in custom_config.read_text(encoding="utf-8")
```

This is the issue-level regression: it exercises the same subprocess path used by `ZKCLI`, including KB registration and config persistence.

- [ ] **Step 6: Run only the new tests and verify the expected RED state.**

Run from the worktree:

```bash
cd /home/elling/git-repo/github/jfox/.pi/worktrees/issue-460-test-config-isolation
ZK_TEST_MOCK_EMBEDDING=1 uv run pytest tests/unit/test_global_config.py -m 'not embedding and not slow' -q
```

Expected result before production/bootstrap changes: the new pytest-bootstrap test fails because `ZK_CONFIG_PATH` is absent, and the child-process override test resolves the temporary HOME path instead of `custom_config`. Do not proceed until the failure is attributable to the missing behavior rather than a test syntax or collection error.

### Task 2: Implement the minimal configuration isolation

**Files:**

- Modify: `jfox/global_config.py:19`
- Modify: `tests/conftest.py:20-28`

**Interfaces:**

- Consumes: the failing tests from Task 1 and the existing `ZK_KB_ROOT` environment pattern.
- Produces: `DEFAULT_CONFIG_PATH` override and pytest-wide inherited isolation for CLI subprocesses.

- [ ] **Step 1: Implement the environment override in `jfox/global_config.py`.**

Replace the current constant:

```python
DEFAULT_CONFIG_PATH = Path.home() / ".zk_config.json"
```

with:

```python
_config_path_env = os.environ.get("ZK_CONFIG_PATH", "").strip()
DEFAULT_CONFIG_PATH = Path(_config_path_env or (Path.home() / ".zk_config.json")).expanduser()
```

Keep the existing `import os` and preserve `DEFAULT_KB_PATH` unchanged. The expression must be evaluated at module import so a child process can select its path before importing JFox.

- [ ] **Step 2: Set the pytest config path before JFox imports.**

Immediately after the existing line:

```python
os.environ["ZK_KB_ROOT"] = str(_TEST_ROOT)
```

add:

```python
# 隔离全局 KB 注册表；CLI 子进程会继承该环境变量，避免写入真实 ~/.zk_config.json。
os.environ["ZK_CONFIG_PATH"] = str(_TEST_ROOT / "zk_config.json")
```

This must remain before `import pytest` and before the imports from `utils.jfox_cli`, `utils.note_generator`, and `utils.temp_kb`, because those modules transitively import JFox configuration modules.

- [ ] **Step 3: Run the focused test file and verify GREEN.**

Run:

```bash
cd /home/elling/git-repo/github/jfox/.pi/worktrees/issue-460-test-config-isolation
ZK_TEST_MOCK_EMBEDDING=1 uv run pytest tests/unit/test_global_config.py -m 'not embedding and not slow' -q
```

Expected result: all tests in `tests/unit/test_global_config.py` pass, including the new bootstrap, child-process override, fallback, and CLI write-location tests.

- [ ] **Step 4: Run the focused CLI-format regression.**

Run with an external temporary HOME as an additional guard against the current user's config:

```bash
cd /home/elling/git-repo/github/jfox/.pi/worktrees/issue-460-test-config-isolation
TEST_HOME="$(mktemp -d)"
trap 'rm -rf "$TEST_HOME"' EXIT
HOME="$TEST_HOME" USERPROFILE="$TEST_HOME" XDG_CONFIG_HOME="$TEST_HOME/.config" \
  ZK_TEST_MOCK_EMBEDDING=1 \
  uv run pytest tests/test_cli_format.py -m 'not embedding and not slow' --timeout=120 --tb=short -q
```

Expected result: the selected CLI format tests pass and no configuration is written outside the temporary test environment.

### Task 3: Review, lint, and document evidence

**Files:**

- Inspect: `jfox/global_config.py`
- Inspect: `tests/conftest.py`
- Inspect: `tests/unit/test_global_config.py`
- Inspect: `docs/superpowers/specs/2026-08-30-test-config-isolation-design.md`

**Interfaces:**

- Consumes: the green implementation from Task 2.
- Produces: verified issue evidence and a clean, minimal diff ready for local code review.

- [ ] **Step 1: Inspect the diff for scope and import-order regressions.**

Run:

```bash
git -C /home/elling/git-repo/github/jfox/.pi/worktrees/issue-460-test-config-isolation diff --check
git -C /home/elling/git-repo/github/jfox/.pi/worktrees/issue-460-test-config-isolation status --short
git -C /home/elling/git-repo/github/jfox/.pi/worktrees/issue-460-test-config-isolation diff --stat
git -C /home/elling/git-repo/github/jfox/.pi/worktrees/issue-460-test-config-isolation diff -- jfox/global_config.py tests/conftest.py tests/unit/test_global_config.py
```

Confirm that only the planned production/test files changed, the spec and plan are present, no real HOME path is embedded in tests, and no unrelated cleanup or CLI behavior changed.

- [ ] **Step 2: Run fast unit coverage for the changed modules.**

Run:

```bash
cd /home/elling/git-repo/github/jfox/.pi/worktrees/issue-460-test-config-isolation
TEST_HOME="$(mktemp -d)"
trap 'rm -rf "$TEST_HOME"' EXIT
HOME="$TEST_HOME" USERPROFILE="$TEST_HOME" XDG_CONFIG_HOME="$TEST_HOME/.config" \
  ZK_TEST_MOCK_EMBEDDING=1 \
  uv run pytest tests/unit/test_global_config.py tests/unit/test_kb_manager.py \
  -m 'not embedding and not slow' --timeout=120 --tb=short -q
```

Expected result: zero failures.

- [ ] **Step 3: Run formatting/static checks for changed Python files.**

Run:

```bash
cd /home/elling/git-repo/github/jfox/.pi/worktrees/issue-460-test-config-isolation
uv run black --check jfox/global_config.py tests/conftest.py tests/unit/test_global_config.py
uv run ruff check jfox/global_config.py tests/conftest.py tests/unit/test_global_config.py
```

Expected result: both commands exit successfully.

- [ ] **Step 4: Record the verification result in the issue.**

After tests and checks pass, add a concise issue comment describing the implemented files and exact commands/results. Do not claim a PR, push, or merge until the user explicitly authorizes those operations.

- [ ] **Step 5: Stop at the push/PR gate.**

Do not commit, push, create a PR, add review labels, or merge automatically. Report the worktree path, changed files, test evidence, and any residual risks to the user, then wait for explicit authorization for the next GitHub operation.
