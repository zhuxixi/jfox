"""#559 nightly 脚本环境契约静态测试。

守护 scripts/nightly_test.sh 的安装面（--extra dev --extra embed + --frozen）、
embed 守卫 wiring（check-embed-env + --no-sync）、rc==4 环境失败不提 issue 分支。
仿 #519 的 test_pyproject_embed_extra.py 静态断言先例。
"""

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts" / "nightly_test.sh"


def parse_sync_extras(script_text: str) -> set[str]:
    """提取 uv sync 命令行本体里的 --extra 值（注释与日志文案不算）。"""
    extras: set[str] = set()
    for line in script_text.splitlines():
        stripped = line.strip()
        if not stripped.startswith("uv sync"):
            continue
        for m in re.finditer(r"--extra[= ]([\w-]+)", stripped):
            extras.add(m.group(1))
    return extras


class TestParseSyncExtras:
    def test_parses_multiple_extras(self):
        assert parse_sync_extras("    uv sync --frozen --extra dev --extra embed") == {
            "dev",
            "embed",
        }

    def test_single_extra(self):
        assert parse_sync_extras("uv sync --frozen --extra dev") == {"dev"}

    def test_ignores_comments_and_log_text(self):
        text = (
            "# uv sync --extra old\n"
            '  log "ERROR: 检查 uv sync 是否带 --extra embed（#519/#559）"\n'
            "    uv run pytest tests/ -v --tb=short -ra\n"
        )
        assert parse_sync_extras(text) == set()


class TestNightlyScriptEnv:
    def _script(self) -> str:
        return SCRIPT.read_text(encoding="utf-8")

    def test_sync_installs_dev_and_embed_extras_frozen(self):
        text = self._script()
        assert {"dev", "embed"} <= parse_sync_extras(text)
        for line in text.splitlines():
            if line.strip().startswith("uv sync"):
                assert "--frozen" in line

    def test_embed_guard_wired_with_no_sync(self):
        text = self._script()
        assert "check-embed-env" in text
        assert "uv run --no-sync python scripts/nightly_test_helpers.py check-embed-env" in text

    def test_env_failure_exit_code_skips_issue_creation(self):
        assert '"$rc" -eq 4' in self._script()

    def test_ref_debug_mode_present(self):
        text = self._script()
        assert "--ref)" in text
        assert "${NIGHTLY_REF:-origin/main}" in text

    def test_ref_mode_skips_backup_and_issue_filing(self):
        text = self._script()
        # 备份检查与提 issue 两处都必须让位于调试模式。
        # 逐一锚定两处守卫：整体 `in` 断言只命中一处时，删除另一处的回归不会被发现。
        assert 'if [[ "$DRY_RUN" -eq 1 || -n "$NIGHTLY_REF" ]]; then' in text  # 备份检查门
        assert 'if [[ -n "$NIGHTLY_REF" ]]; then' in text  # 失败分支不提 issue 门
        assert text.count('-n "$NIGHTLY_REF"') >= 2
