"""碎片检测器：根据 CC 事件推断 fragment_type 与 content（纯逻辑，无 I/O）。"""

import json
from typing import Optional, Tuple

from ..global_config import FragmentCaptureConfig


def classify(event: dict, config: FragmentCaptureConfig) -> Tuple[str, Optional[str]]:
    """根据事件推断 (fragment_type, content)。

    - UserPromptSubmit: 命中纠正词→correction（优先），命中决策词→decision，否则 user_input
    - PostToolUse:      tool_call，content=tool_response 序列化后截断
    - Stop:             session_summary，content 留空（由 service 填本轮汇总）
    - 其它:             user_input 兜底
    """
    name = event.get("hook_event_name")
    limit = config.max_content_chars

    if name == "PostToolUse":
        # 按键存在性判断：tool_response 为 falsy 但合法（空串/{}/[]，如 grep 无输出）
        # 时不应回退到 tool_input（语义错误）
        if "tool_response" in event:
            resp = event["tool_response"]
        else:
            resp = event.get("tool_input", "")
        text = resp if isinstance(resp, str) else json.dumps(resp, ensure_ascii=False, default=str)
        return "tool_call", text[:limit]

    if name == "UserPromptSubmit":
        prompt = event.get("prompt", "") or ""
        if any(k in prompt for k in config.correction_keywords):
            ftype = "correction"
        elif any(k in prompt for k in config.decision_keywords):
            ftype = "decision"
        else:
            ftype = "user_input"
        return ftype, prompt[:limit]

    if name == "Stop":
        return "session_summary", None

    return "user_input", None


__all__ = ["classify"]
