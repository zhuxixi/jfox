"""JFox 内部系统来源标记，用于碎片采集过滤。

这些来源产生的 Claude Code session 不应进入 fragments 链路，否则会造成自引用死循环
（例如 auto-summary 生成的摘要被 gem-synth 合成，合成又产生新碎片）。
"""

INTERNAL_SOURCES = frozenset({"auto-summary", "gem-synth"})
