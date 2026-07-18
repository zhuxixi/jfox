"""unit 测试公共 fixture。"""

import pytest


@pytest.fixture(autouse=True)
def _clear_lifecycle_hooks():
    """每测前后清空 note.py 全局生命周期钩子，防跨测试泄漏。

    register() 写模块级 _LIFECYCLE_HOOKS（不随测试结束自动回收）；此 autouse
    fixture 让任何 unit 测试触碰 note.py 生命周期路径都从干净状态开始，新测试
    文件无需各自复刻 clear() boilerplate。
    """
    from jfox.note import _LIFECYCLE_HOOKS

    _LIFECYCLE_HOOKS.clear()
    yield
    _LIFECYCLE_HOOKS.clear()
