# jfox self-update 命令 Implementation Plan

> **For agentic workers:** implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a `jfox update` command that detects the current installation method (dev / uv / pipx / pip) and invokes the appropriate upgrade command, showing before/after version info and providing manual fallback guidance on failure.

**Architecture:** A new `update` Typer command in `jfox/cli.py` plus helper functions for install-method detection and upgrade command execution. Detection is path-based with command fallbacks. A unit test file `tests/unit/test_update.py` mocks filesystem paths and subprocess calls.

**Tech Stack:** Python 3.10+, Typer, Rich, pytest, unittest.mock.

**Spec:** `docs/superpowers/specs/2026-06-18-self-update-command-design.md`

**Work context:** Work in the isolated worktree `/home/elling/git-repo/github/jfox-wt-238` on branch `feat/issue-238-self-update` (based off `main`). All paths below are relative to that worktree root.

---

## File Structure

| File | Action | Responsibility |
|------|--------|----------------|
| `jfox/cli.py` | **Modify** | Add `_detect_install_method`, `_build_upgrade_command`, `_run_upgrade`, `_update_impl`, and `update` Typer command. |
| `tests/unit/test_update.py` | **Create** | Unit tests for detection, command selection, JSON output, dev-mode prompt, and failure handling. |
| `README.md` | **Modify** | Add `jfox update` to the command reference table. |
| `docs/installation.md` | **Modify** | Add an "Upgrade" section with `jfox update` and manual fallbacks. |

---

## Task 1: Implement install-method detection helpers

**Files:** `jfox/cli.py`

- [ ] **Step 1: Add `_is_dev_installation` helper**

  Determine development mode by checking whether `jfox.__file__` resolves to a source tree containing `pyproject.toml` with `project.name == "jfox-cli"` and a `.git` directory, or whether the path indicates an editable install (`.egg-link`).

- [ ] **Step 2: Add `_is_uv_tool_installation` helper**

  Run `uv tool dir` to obtain the uv tools root. Return `True` if `jfox.__file__` is relative to `<uv-tool-dir>/jfox-cli/`. If `uv` is unavailable, fall back to path-segment matching (`uv/tools/jfox-cli/`).

- [ ] **Step 3: Add `_is_pipx_installation` helper**

  Run `pipx environment --value PIPX_HOME` to obtain pipx home. Return `True` if `jfox.__file__` is relative to `<pipx-home>/venvs/jfox-cli/`. If `pipx` is unavailable, fall back to path-segment matching (`pipx/venvs/jfox-cli/`).

- [ ] **Step 4: Add `_detect_install_method` helper**

  Apply the detection order: dev → uv → pipx → pip. Return a string identifier (`"dev"`, `"uv"`, `"pipx"`, `"pip"`).

---

## Task 2: Implement upgrade execution and version comparison

**Files:** `jfox/cli.py`

- [ ] **Step 1: Add `_build_upgrade_command` helper**

  Map the detected install method to the concrete command list:
  - `"uv"` → `["uv", "tool", "upgrade", "jfox-cli"]`
  - `"pipx"` → `["pipx", "upgrade", "jfox-cli"]`
  - `"pip"` → `[sys.executable, "-m", "pip", "install", "--upgrade", "jfox-cli"]`
  - `"dev"` → return `None`

- [ ] **Step 2: Add `_run_upgrade` helper**

  Use `subprocess.run(..., check=True, capture_output=True, text=True)` to execute the command. On success return stdout; on `CalledProcessError` raise a custom exception or return an error dict. Surface stderr to the user.

- [ ] **Step 3: Add `_get_installed_version` helper**

  Run `jfox --version` via subprocess and parse the version string. Return `"unknown"` if the call fails.

---

## Task 3: Wire up the `update` Typer command

**Files:** `jfox/cli.py`

- [ ] **Step 1: Add `_update_impl` internal function**

  1. Read current `__version__`.
  2. Detect install method.
  3. If dev, return a result dict with `success=True`, `method="dev"`, and an instruction string.
  4. Build and run the upgrade command.
  5. Call `_get_installed_version` for the after version.
  6. Return a result dict: `success`, `method`, `previous_version`, `current_version`, `command`, `output`.

- [ ] **Step 2: Add `update` Typer command**

  Support `--format json/table` and `--json` shortcut. Wrap the implementation in a try/except, print table or JSON output, and exit with code 1 on failure.

---

## Task 4: Add unit tests

**Files:** `tests/unit/test_update.py`

- [ ] **Step 1: Test dev-mode detection**

  Mock `jfox.__file__` to a source tree path with `pyproject.toml` and `.git/`. Assert `jfox update` prints the dev-mode instruction and does not invoke subprocess.

- [ ] **Step 2: Test uv / pipx / pip command selection**

  Mock `jfox.__file__` to each tool's typical site-packages path and assert the correct subprocess command is invoked.

- [ ] **Step 3: Test JSON output**

  Run `jfox update --json` and verify the parsed JSON contains expected keys.

- [ ] **Step 4: Test upgrade failure handling**

  Make `subprocess.run` raise `CalledProcessError`. Assert exit code 1 and manual command guidance appears in output/JSON.

- [ ] **Step 5: Test version before/after display**

  Mock `jfox.__version__` and the post-upgrade `jfox --version` subprocess to verify both versions appear.

---

## Task 5: Update documentation

**Files:** `README.md`, `docs/installation.md`

- [ ] **Step 1: Add `jfox update` to README command table**

  Place it under a new "Self-update" row or in the most appropriate existing section.

- [ ] **Step 2: Add upgrade section to `docs/installation.md`**

  Document `jfox update` and the manual fallbacks for each install method.

---

## Task 6: Run tests and static checks

- [ ] **Step 1: Run the new unit tests**

  ```bash
  uv run pytest tests/unit/test_update.py -v
  ```

- [ ] **Step 2: Run fast unit tests**

  ```bash
  uv run pytest tests/unit/ -m "not embedding and not slow" -q
  ```

- [ ] **Step 3: Run ruff lint**

  ```bash
  uv run ruff check jfox/cli.py tests/unit/test_update.py
  ```

---

## Task 7: Commit and create PR

- [ ] **Step 1: Stage and commit changes**

  Use Conventional Commits:

  ```bash
  git add jfox/cli.py tests/unit/test_update.py README.md docs/installation.md docs/superpowers/
  git commit -m "feat(cli): add self-update command (jfox update)"
  git commit -m "docs(readme): document jfox update command" -- README.md docs/installation.md
  git commit -m "docs(superpowers): add self-update design and plan"
  ```

- [ ] **Step 2: Push branch and create PR**

  ```bash
  git push -u origin feat/issue-238-self-update
  gh pr create --title "feat(cli): add self-update command" --body "Closes #238" --base main
  ```

- [ ] **Step 3: Wait for CI**

  Monitor the PR checks and address any failures.
