"""session-batch judge 编排测试：claim → 证据 → runner → candidate → 记账。"""

from unittest.mock import MagicMock, patch

import pytest

from jfox.prompts.judge import judge_prompts
from jfox.prompts.runner import RunnerResult
from jfox.prompts.store import PromptStore

pytestmark = [pytest.mark.unit, pytest.mark.fast]


def _store_with_prompts(tmp_path, n=3, session_id="s1", transcript_path="/tmp/t.jsonl"):
    store = PromptStore(db_path=tmp_path / "fragments.db")
    for i in range(n):
        ev = {
            "hook_event_name": "UserPromptSubmit",
            "session_id": session_id,
            "prompt": f"测试问题{i}",
        }
        if transcript_path:
            ev["transcript_path"] = transcript_path
        store.insert_prompt(ev, source_key=f"capture:c{i}")
    return store


def _mock_runner_output(prompt_ids, classification="new"):
    """构造合法 runner 输出。"""
    items = []
    for pid in prompt_ids:
        item = {
            "prompt_id": pid,
            "classification": classification,
            "reason": f"判断理由{pid}",
            "confidence": 0.8,
            "matched_note_ids": [],
            "matched_prompt_ids": [],
            "matched_unresolved_prompt_ids": [],
        }
        if classification == "new":
            item["draft"] = {
                "title": f"候选标题{pid}",
                "content": f"这是候选笔记正文 {pid}",
                "knowledge_type": "factual",
                "grounded_by": [],
            }
        items.append(item)
    return RunnerResult(ok=True, items=items)


# ---------------------------------------------------------------------------
# 基本流程
# ---------------------------------------------------------------------------


def test_judge_creates_judgments_for_all_prompts(tmp_path):
    store = _store_with_prompts(tmp_path, n=3)
    with (
        patch("jfox.prompts.judge.run_runner") as mock_runner,
        patch("jfox.prompts.judge.fetch_judgment_grounding") as mock_ground,
        patch("jfox.prompts.judge.read_transcript_safe") as mock_transcript,
    ):
        mock_runner.return_value = _mock_runner_output([1, 2, 3])
        mock_ground.return_value = MagicMock(evidence=[], unavailable=False)
        mock_transcript.return_value = MagicMock(
            total_messages=0, messages=[], user_texts=[], user_indices=[]
        )
        report = judge_prompts("default", store=store, allow_remote=True)

    assert report.total == 3
    assert report.succeeded == 3
    for pid in [1, 2, 3]:
        j = store.get_judgment("default", pid)
        assert j["judgment_state"] == "succeeded"
        assert j["classification"] == "new"
        assert j["disposition"] == "pending"


def test_judge_respects_default_limit(tmp_path):
    store = _store_with_prompts(tmp_path, n=10)
    with (
        patch("jfox.prompts.judge.run_runner") as mock_runner,
        patch("jfox.prompts.judge.fetch_judgment_grounding") as mock_ground,
        patch("jfox.prompts.judge.read_transcript_safe") as mock_transcript,
    ):
        mock_runner.side_effect = lambda task, cfg, allow_remote: _mock_runner_output(
            [item["prompt_id"] for item in task["items"]]
        )
        mock_ground.return_value = MagicMock(evidence=[], unavailable=False)
        mock_transcript.return_value = MagicMock(
            total_messages=0, messages=[], user_texts=[], user_indices=[]
        )
        report = judge_prompts("default", store=store, limit=5, allow_remote=True)
    assert report.total == 5  # 只处理 5 条


def test_judge_runner_failure_fails_items(tmp_path):
    store = _store_with_prompts(tmp_path, n=2)
    with (
        patch("jfox.prompts.judge.run_runner") as mock_runner,
        patch("jfox.prompts.judge.fetch_judgment_grounding") as mock_ground,
        patch("jfox.prompts.judge.read_transcript_safe") as mock_transcript,
    ):
        mock_runner.return_value = RunnerResult(ok=False, error="runner down")
        mock_ground.return_value = MagicMock(evidence=[], unavailable=False)
        mock_transcript.return_value = MagicMock(
            total_messages=0, messages=[], user_texts=[], user_indices=[]
        )
        report = judge_prompts("default", store=store, allow_remote=True)

    assert report.succeeded == 0
    assert report.failed == 2
    for pid in [1, 2]:
        j = store.get_judgment("default", pid)
        assert j["judgment_state"] == "failed"
        assert "runner down" in j["last_error"]


def test_judge_grounding_unavailable_fails_items(tmp_path):
    """grounding 异常 → item failed，不调用 runner。"""
    store = _store_with_prompts(tmp_path, n=1)
    with (
        patch("jfox.prompts.judge.fetch_judgment_grounding") as mock_ground,
        patch("jfox.prompts.judge.run_runner") as mock_runner,
    ):
        mock_ground.return_value = MagicMock(evidence=[], unavailable=True, error="db down")
        report = judge_prompts("default", store=store, allow_remote=True)

    assert report.failed == 1
    mock_runner.assert_not_called()  # grounding 异常不调 runner
    j = store.get_judgment("default", 1)
    assert j["judgment_state"] == "failed"


def test_judge_skips_succeeded_on_second_run(tmp_path):
    """成功的 judgment 不被第二次 judge 重复处理。"""
    store = _store_with_prompts(tmp_path, n=2)
    with (
        patch("jfox.prompts.judge.run_runner") as mock_runner,
        patch("jfox.prompts.judge.fetch_judgment_grounding") as mock_ground,
        patch("jfox.prompts.judge.read_transcript_safe") as mock_transcript,
    ):
        mock_runner.side_effect = lambda task, cfg, allow_remote: _mock_runner_output(
            [item["prompt_id"] for item in task["items"]], classification="recorded"
        )
        mock_ground.return_value = MagicMock(evidence=[], unavailable=False)
        mock_transcript.return_value = MagicMock(
            total_messages=0, messages=[], user_texts=[], user_indices=[]
        )
        judge_prompts("default", store=store, allow_remote=True)
        # 第二次 judge：全部已成功，不该再选
        report2 = judge_prompts("default", store=store, allow_remote=True)

    assert report2.total == 0  # 没有新的待判断


# ---------------------------------------------------------------------------
# session 分组与 transcript 复用
# ---------------------------------------------------------------------------


def test_judge_reads_transcript_once_per_session(tmp_path):
    """同一 session 的多个 prompt 只读一次 transcript。"""
    store = _store_with_prompts(tmp_path, n=3, session_id="same-session")
    with (
        patch("jfox.prompts.judge.run_runner") as mock_runner,
        patch("jfox.prompts.judge.fetch_judgment_grounding") as mock_ground,
        patch("jfox.prompts.judge.read_transcript_safe") as mock_transcript,
    ):
        mock_runner.side_effect = lambda task, cfg, allow_remote: _mock_runner_output(
            [item["prompt_id"] for item in task["items"]], classification="recorded"
        )
        mock_ground.return_value = MagicMock(evidence=[], unavailable=False)
        mock_transcript.return_value = MagicMock(
            total_messages=0, messages=[], user_texts=[], user_indices=[]
        )
        judge_prompts("default", store=store, allow_remote=True)

    # read_transcript_safe 对同一 session 只调一次（3 个 prompt 同 session）
    assert mock_transcript.call_count == 1
    # 但 runner 只调一次（一个 batch）
    assert mock_runner.call_count == 1


def test_judge_batches_by_session_limit(tmp_path):
    """同一 session 超过 session_batch_limit 时拆 batch。"""
    store = _store_with_prompts(tmp_path, n=25)  # > session_batch_limit=20
    with (
        patch("jfox.prompts.judge.run_runner") as mock_runner,
        patch("jfox.prompts.judge.fetch_judgment_grounding") as mock_ground,
        patch("jfox.prompts.judge.read_transcript_safe") as mock_transcript,
    ):
        mock_runner.side_effect = lambda task, cfg, allow_remote: _mock_runner_output(
            [item["prompt_id"] for item in task["items"]], classification="recorded"
        )
        mock_ground.return_value = MagicMock(evidence=[], unavailable=False)
        mock_transcript.return_value = MagicMock(
            total_messages=0, messages=[], user_texts=[], user_indices=[]
        )
        report = judge_prompts(
            "default",
            store=store,
            all_items=True,
            session_batch_limit=10,
            allow_remote=True,
        )

    # 25 条 / batch 10 → 3 个 batch
    assert mock_runner.call_count == 3
    assert report.succeeded == 25


# ---------------------------------------------------------------------------
# retry-failed
# ---------------------------------------------------------------------------


def test_judge_retry_failed_reselects_failed(tmp_path):
    store = _store_with_prompts(tmp_path, n=1)
    with (
        patch("jfox.prompts.judge.run_runner") as mock_runner,
        patch("jfox.prompts.judge.fetch_judgment_grounding") as mock_ground,
        patch("jfox.prompts.judge.read_transcript_safe") as mock_transcript,
    ):
        mock_runner.return_value = RunnerResult(ok=False, error="first fails")
        mock_ground.return_value = MagicMock(evidence=[], unavailable=False)
        mock_transcript.return_value = MagicMock(
            total_messages=0, messages=[], user_texts=[], user_indices=[]
        )
        judge_prompts("default", store=store, allow_remote=True)

        # retry-failed：failed 行重新选中
        mock_runner.return_value = _mock_runner_output([1], classification="recorded")
        report = judge_prompts("default", store=store, retry_failed=True, allow_remote=True)

    assert report.succeeded == 1
    j = store.get_judgment("default", 1)
    assert j["judgment_state"] == "succeeded"
    assert j["classification"] == "recorded"


# ---------------------------------------------------------------------------
# remote consent
# ---------------------------------------------------------------------------


def test_judge_remote_without_consent_fails(tmp_path):
    store = _store_with_prompts(tmp_path, n=1)
    with patch("jfox.prompts.judge.fetch_judgment_grounding") as mock_ground:
        mock_ground.return_value = MagicMock(evidence=[], unavailable=False)
        report = judge_prompts("default", store=store, allow_remote=False)

    assert report.failed == 1
    j = store.get_judgment("default", 1)
    assert "consent" in (j["last_error"] or "").lower()
