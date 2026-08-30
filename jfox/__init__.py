"""JFox - Zettelkasten 知识管理工具"""

__version__ = "1.12.1"
__author__ = "User"
__email__ = "user@example.com"


# 注册 gem_synth dedup 生命周期订阅：note.py 广播 post_delete/archive/promote/reject
# 事件，gem_synth 订阅同步 dedup 表。放包 __init__——任何 `import jfox.*`（含 CLI、
# 库式 `from jfox.note import ...`、未来 daemon/脚本调用方）都触发本模块加载 → 订阅
# 就位，避免 register 依赖单一入口（cli.py）的隐式调用顺序耦合。分层约束：note.py
# 不依赖 gem_synth，反向通知由本包顶层接线（__init__ 非核心存储层）。
from .gem_synth.lifecycle import register as _register_gem_synth_lifecycle

_register_gem_synth_lifecycle()
