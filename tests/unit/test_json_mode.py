"""
测试类型: 单元测试
目标模块: jfox.cli._json_mode_requested
预估耗时: < 1秒
"""

import pytest

pytestmark = [pytest.mark.unit, pytest.mark.fast]

from jfox.cli import _json_mode_requested


class TestJsonModeRequested:
    @pytest.mark.parametrize(
        "argv,expected",
        [
            (["jfox", "add", "--json"], True),
            (["jfox", "search", "x", "--json"], True),
            (["jfox", "add", "-f", "json"], True),
            (["jfox", "add", "--format", "json"], True),
            (["jfox", "add", "--format=json"], True),
            (["jfox", "add", "-fjson"], True),
            (["jfox", "add", "--format", "table", "--format", "json"], True),
            (["jfox", "add", "--format", "json", "--format", "table"], False),
            (["jfox", "add", "-f", "table", "-f", "json"], True),
            (["jfox", "add", "--format", "table"], False),
            (["jfox", "add"], False),
            (["jfox", "list"], False),
        ],
    )
    def test_detection(self, argv, expected):
        assert _json_mode_requested(argv) is expected
