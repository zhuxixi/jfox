"""外部 runner 安全测试：argv 构建、保留参数拒绝、stdin 传入、进程组清理。"""

from unittest.mock import patch

import pytest

from jfox.global_config import PromptJudgeConfig
from jfox.prompts.runner import (
    build_pi_argv,
    run_runner,
    validate_runner_output,
)

pytestmark = [pytest.mark.unit, pytest.mark.fast]


# ---------------------------------------------------------------------------
# build_pi_argv
# ---------------------------------------------------------------------------


def test_build_pi_argv_includes_safety_flags():
    cfg = PromptJudgeConfig()
    argv = build_pi_argv(cfg)
    assert argv[0] == "pi"
    assert "--print" in argv
    assert "--model" in argv
    assert argv[argv.index("--model") + 1] == cfg.model
    assert "--thinking" in argv
    assert argv[argv.index("--thinking") + 1] == "off"
    assert "--no-tools" in argv
    assert "--no-session" in argv
    assert "--no-extensions" in argv
    assert "--no-skills" in argv
    assert "--no-context-files" in argv
    assert "--no-approve" in argv
    # 内置 system instruction 不可被配置覆盖
    assert "--append-system-prompt" in argv


def test_build_pi_argv_configurable_model():
    cfg = PromptJudgeConfig(model="ollama/some-other-model")
    argv = build_pi_argv(cfg)
    assert argv[argv.index("--model") + 1] == "ollama/some-other-model"


# ---------------------------------------------------------------------------
# extra_args 保留参数拒绝
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "bad_arg",
    [
        ["--tools", "bash"],
        ["--session"],
        ["--extension", "./evil.ts"],
        ["--skill", "evil"],
        ["--context-files"],
        ["--approve"],
        ["--system-prompt", "override"],
        ["--append-system-prompt", "override"],
        ["--model", "hijack"],
        ["--thinking", "high"],
    ],
)
def test_extra_args_cannot_override_reserved_flags(bad_arg):
    """试图覆盖保留安全参数的 extra_args 被拒绝。"""
    with pytest.raises(ValueError, match="保留安全参数"):
        build_pi_argv(PromptJudgeConfig(extra_args=bad_arg))


def test_extra_args_can_add_non_reserved():
    argv = build_pi_argv(PromptJudgeConfig(extra_args=["--verbose"]))
    assert "--verbose" in argv


# ---------------------------------------------------------------------------
# remote consent
# ---------------------------------------------------------------------------


def test_remote_runner_requires_consent():
    cfg = PromptJudgeConfig(runner_scope="remote", allow_remote=False)
    result = run_runner({"items": []}, cfg, allow_remote=False)
    assert result.ok is False
    assert "consent" in result.error.lower()


def test_remote_runner_with_consent_proceeds():
    cfg = PromptJudgeConfig(runner_scope="remote")
    with patch("jfox.prompts.runner._invoke_subprocess") as mock_invoke:
        mock_invoke.return_value = ('{"items": []}', "")
        result = run_runner({"items": []}, cfg, allow_remote=True)
        assert result.ok is True
        mock_invoke.assert_called_once()


def test_local_runner_no_consent_needed():
    cfg = PromptJudgeConfig(runner_scope="local")
    with patch("jfox.prompts.runner._invoke_subprocess") as mock_invoke:
        mock_invoke.return_value = ('{"items": []}', "")
        result = run_runner({"items": []}, cfg, allow_remote=False)
        assert result.ok is True


# ---------------------------------------------------------------------------
# PromptJudgeConfig 校验
# ---------------------------------------------------------------------------


def test_claim_timeout_must_exceed_runner_timeout():
    """claim_timeout_seconds 必须大于 timeout_seconds + 60。"""
    with pytest.raises(ValueError, match="claim_timeout"):
        PromptJudgeConfig(timeout_seconds=300, claim_timeout_seconds=350)  # 350 < 360


def test_custom_command_must_be_list():
    """runner=argv 时 custom_command 必须是列表，不能是 shell 字符串。"""
    with pytest.raises(ValueError, match="argv"):
        PromptJudgeConfig(runner="argv", custom_command="bash -c 'evil'")


def test_custom_command_valid_list():
    cfg = PromptJudgeConfig(runner="argv", custom_command=["/usr/local/bin/my-runner"])
    assert cfg.custom_command == ["/usr/local/bin/my-runner"]


# ---------------------------------------------------------------------------
# RunnerResult / validate_runner_output
# ---------------------------------------------------------------------------


def _valid_output(prompt_ids=(1, 2)):
    items = []
    for pid in prompt_ids:
        items.append(
            {
                "prompt_id": pid,
                "classification": "new",
                "reason": "KB 无覆盖",
                "confidence": 0.8,
                "matched_note_ids": ["n1"],
                "matched_prompt_ids": [],
                "matched_unresolved_prompt_ids": [],
                "draft": {
                    "title": f"标题{pid}",
                    "content": "正文",
                    "knowledge_type": "factual",
                    "grounded_by": ["笔记A"],
                },
            }
        )
    return {"items": items}


def test_validate_output_valid():
    result = validate_runner_output(_valid_output(), expected_ids=[1, 2])
    assert result.ok is True
    assert len(result.items) == 2


def test_validate_output_missing_id_fails():
    output = _valid_output(prompt_ids=(1,))  # 缺 id=2
    result = validate_runner_output(output, expected_ids=[1, 2])
    assert result.ok is False


def test_validate_output_unknown_id_fails():
    output = _valid_output(prompt_ids=(1, 99))  # 99 不在 expected
    result = validate_runner_output(output, expected_ids=[1])
    assert result.ok is False


def test_validate_output_duplicate_id_fails():
    output = _valid_output(prompt_ids=(1, 1))
    result = validate_runner_output(output, expected_ids=[1])
    assert result.ok is False


def test_validate_output_invalid_classification_fails():
    output = _valid_output(prompt_ids=(1,))
    output["items"][0]["classification"] = "some_invalid"
    result = validate_runner_output(output, expected_ids=[1])
    assert result.ok is False


def test_validate_output_confidence_out_of_range_fails():
    output = _valid_output(prompt_ids=(1,))
    output["items"][0]["confidence"] = 1.5
    result = validate_runner_output(output, expected_ids=[1])
    assert result.ok is False


def test_validate_output_needs_review_discards_draft():
    output = _valid_output(prompt_ids=(1,))
    output["items"][0]["classification"] = "needs_review"
    result = validate_runner_output(output, expected_ids=[1])
    assert result.ok is True
    # needs_review 即使带 draft 也丢弃
    assert result.items[0].get("draft") is None


def test_validate_output_new_requires_draft():
    output = _valid_output(prompt_ids=(1,))
    del output["items"][0]["draft"]
    result = validate_runner_output(output, expected_ids=[1])
    assert result.ok is False


def test_validate_output_non_new_must_not_have_draft():
    output = _valid_output(prompt_ids=(1,))
    output["items"][0]["classification"] = "recorded"
    # recorded 不该有 draft
    result = validate_runner_output(output, expected_ids=[1])
    assert result.ok is False


def test_validate_output_json_with_surrounding_text():
    """JSON 前后带解释文本仍可解析。"""
    raw = (
        "以下是结果：\n"
        + '{"items": [{"prompt_id": 1, "classification": "recorded", "reason": "已有", "confidence": 0.9, "matched_note_ids": [], "matched_prompt_ids": [], "matched_unresolved_prompt_ids": []}]}'
        + "\n完"
    )
    import json

    parsed = json.loads(raw[raw.index("{") : raw.rindex("}") + 1])
    result = validate_runner_output(parsed, expected_ids=[1])
    assert result.ok is True


# ---------------------------------------------------------------------------
# subprocess 隔离（集成级：实际启动 sleep 进程验证超时清理）
# ---------------------------------------------------------------------------


def test_runner_timeout_kills_process_group():
    """runner 超时后进程组被清理，不留孤儿。"""
    from jfox.prompts.runner import _invoke_subprocess

    # 直接调 _invoke_subprocess，绕过 PromptJudgeConfig 的 timeout>=30 校验
    cfg = PromptJudgeConfig()
    object.__setattr__(cfg, "timeout_seconds", 1)  # 直接改属性绕过 post_init
    with pytest.raises(TimeoutError, match="超时"):
        _invoke_subprocess(["sleep", "60"], "{}", cfg)


def test_runner_sets_internal_session_env():
    """runner 子进程设置 JFOX_INTERNAL_SESSION=prompt-judge。"""
    from jfox.prompts.runner import _invoke_subprocess

    cfg = PromptJudgeConfig(runner_scope="local")
    # 用真实子进程（echo 空输出）验证 env 传递
    stdout, stderr = _invoke_subprocess(["sh", "-c", 'echo "$JFOX_INTERNAL_SESSION"'], "{}", cfg)
    assert stdout.strip() == "prompt-judge"


def test_short_flag_aliases_cannot_bypass_reserved_flags():
    """-t/-e/-a 等 pi 短 flag 别名不得绕过保留参数黑名单。"""
    for bad in (
        ["-t", "bash"],
        ["-e", "/tmp/evil.py"],
        ["-a"],
        ["--session-id", "x"],
        ["--fork", "s"],
    ):
        with pytest.raises(ValueError, match="保留安全参数"):
            build_pi_argv(PromptJudgeConfig(extra_args=list(bad)))


def test_validate_runner_output_rejects_phantom_evidence_ids():
    """matched_note_ids 引用未提供的 evidence 时拒绝（防幻觉引用）。"""
    output = {
        "items": [
            {
                "prompt_id": 1,
                "classification": "repeated",
                "reason": "r",
                "confidence": 0.9,
                "matched_note_ids": ["ghost-note"],
            }
        ]
    }
    result = validate_runner_output(output, [1], evidence_note_ids={"real-note"})
    assert result.ok is False
    assert "未提供" in result.error


def test_validate_runner_output_accepts_real_evidence_ids():
    output = {
        "items": [
            {
                "prompt_id": 1,
                "classification": "repeated",
                "reason": "r",
                "confidence": 0.9,
                "matched_note_ids": ["real-note"],
            }
        ]
    }
    result = validate_runner_output(output, [1], evidence_note_ids={"real-note"})
    assert result.ok is True
    assert result.items[0]["matched_note_ids"] == ["real-note"]
