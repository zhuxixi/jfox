"""JFox - Zettelkasten 知识管理工具"""

__version__ = "1.13.0"
__author__ = "User"
__email__ = "user@example.com"


# gem_synth 自动合成已退役（#399）：dedup 表生命周期由 jfox.dedup_lifecycle 维护，
# prompt 判断生命周期由 jfox.prompts.lifecycle 维护（下方已注册）。

# dedup 表生命周期（接续旧 gem_synth/lifecycle 职责，防已删笔记 embedding 残留误拦 add）：
from .dedup_lifecycle import register_lifecycle as _register_dedup_lifecycle

_register_dedup_lifecycle()

# prompt 判断生命周期（#399）：candidate 直接 promote/reject → judgment 同步。
# 放包 __init__ 与上同理由：任何 import jfox.* 都先注册（幂等）。
from .prompts.lifecycle import register_hooks as _register_prompt_hooks

_register_prompt_hooks()
