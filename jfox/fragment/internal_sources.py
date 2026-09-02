"""JFox 内部系统来源标记，用于碎片采集过滤。

这些来源产生的 Claude Code session 不应进入采集链路，否则会造成自引用死循环
（auto-summary 摘要、已退役的 gem-synth 合成、prompt-judge 判断调用）。

注意：packages/cc-plugin/hooks/fragment-capture.sh 中的 case 模式必须与此处保持一致；
新增/修改来源时请同步更新 hook 脚本，并通过 tests/unit/test_fragment_internal_sources.py
中的同步测试。
"""

INTERNAL_SOURCES = frozenset({"auto-summary", "gem-synth", "prompt-judge"})
