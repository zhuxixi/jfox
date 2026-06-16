from jfox.auto_summary.runner import SYSTEM_PROMPT


def test_system_prompt_requires_five_sections():
    for section in ["背景", "做了什么", "关键决策", "技术细节", "未决事项"]:
        assert section in SYSTEM_PROMPT, f"SYSTEM_PROMPT 缺少章节: {section}"


def test_system_prompt_no_longer_requires_only_three():
    # summary_md 现在应是五段而非三段
    assert "包含五个二级章节" in SYSTEM_PROMPT
