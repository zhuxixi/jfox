"""验证 fragment 内部来源列表在 Python 代码与 hook 脚本中保持一致。"""

import re
from pathlib import Path

from jfox.fragment.internal_sources import INTERNAL_SOURCES

REPO_ROOT = Path(__file__).resolve().parents[2]
HOOK = REPO_ROOT / "packages" / "cc-plugin" / "hooks" / "fragment-capture.sh"


def test_internal_sources_expected_values():
    assert INTERNAL_SOURCES == {"auto-summary", "gem-synth"}


def test_hook_script_matches_internal_sources():
    """hook 脚本中 case 分支的内部来源必须与服务端 INTERNAL_SOURCES 一致。"""
    hook_text = HOOK.read_text(encoding="utf-8")
    # 提取类似：case "${JFOX_INTERNAL_SESSION:-}" in
    #               auto-summary|gem-synth) ... ;;
    #           esac
    match = re.search(
        r'case\s+"\$\{JFOX_INTERNAL_SESSION:-\}"\s+in\s+([^)]+)\)',
        hook_text,
        re.DOTALL,
    )
    assert match, "hook 脚本中未找到 JFOX_INTERNAL_SESSION 的 case 分支"
    hook_sources = {src.strip() for src in match.group(1).split("|")}
    assert hook_sources == INTERNAL_SOURCES
