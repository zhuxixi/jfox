"""JFox - Zettelkasten 知识管理工具"""

__version__ = "1.12.1"
__author__ = "User"
__email__ = "user@example.com"

# gem_synth 自动合成已退役（#399）：prompt 记录 + 按需判断见 jfox.prompts。
# candidate 生命周期同步由 jfox.prompts.lifecycle 提供，CLI 层按需注册；
# 包 __init__ 不再接线任何自动合成订阅。
