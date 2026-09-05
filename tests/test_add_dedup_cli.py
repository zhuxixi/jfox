"""
测试类型: 集成测试（CLI 子进程）
目标: jfox add permanent 防重端到端（#383）

子进程无 daemon → embedding 通道自动降级，标题通道覆盖主路径。
"""

import json
import subprocess
import sys
from pathlib import Path

import pytest

pytestmark = [pytest.mark.integration]

REPO_ROOT = Path(__file__).parent.parent


class TestAddDedupCLI:
    def test_title_duplicate_blocked(self, cli):
        r1 = cli._run("add", "第一条内容", "--title", "Dup-Title-X", "--type", "permanent")
        assert r1.success
        r2 = cli._run("add", "第二条不同内容", "--title", "Dup-Title-X", "--type", "permanent")
        assert r2.returncode == 1
        assert r2.data is not None
        assert r2.data["success"] is False
        assert r2.data["skipped"] == "duplicate"
        assert r2.data["duplicate"]["matched_by"] == "title"
        assert r2.data["duplicate"]["matched_id"] == r1.data["note"]["id"]

    def test_force_bypasses_duplicate(self, cli):
        r1 = cli._run("add", "内容一", "--title", "Dup-Title-F", "--type", "permanent")
        assert r1.success
        r2 = cli._run("add", "内容二", "--title", "Dup-Title-F", "--type", "permanent", "--force")
        assert r2.success
        assert r2.data["success"] is True

    def test_fleeting_not_checked(self, cli):
        cli._run("add", "fleeting 内容", "--title", "Dup-Title-G")
        r2 = cli._run("add", "fleeting 内容", "--title", "Dup-Title-G")
        assert r2.success

    def test_different_title_permanent_passes(self, cli):
        cli._run("add", "正文一", "--title", "Dup-Title-H", "--type", "permanent")
        r2 = cli._run("add", "正文二", "--title", "Dup-Title-H2", "--type", "permanent")
        assert r2.success


class TestJsonPurity:
    def test_add_json_output_pure_even_with_2to1_merge(self, cli):
        """--json 2>&1 合流后输出仍是单段合法 JSON（#383 根因 A 回归测试）。"""
        # 预热：新 KB 首次 BM25 写入时 metadata 缺失会发一条 WARNING（spec D12 已知
        # 残余，走 stderr），先写一次让 metadata 落盘，使被测的“正常成功路径”无告警
        warmup = cli._run("add", "预热正文", "--title", "Json-Pure-Warmup", "--type", "permanent")
        assert warmup.success
        cmd = [
            sys.executable,
            "-m",
            "jfox",
            "add",
            "纯净输出测试正文",
            "--title",
            "Json-Pure-1",
            "--type",
            "permanent",
            "--json",
            "--kb",
            cli.kb_name,
        ]
        r = subprocess.run(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            cwd=str(REPO_ROOT),
        )
        assert r.returncode == 0
        try:
            data = json.loads(r.stdout)
        except json.JSONDecodeError as e:
            # 诊断信息永久保留：污染源随环境变化（daemon 有无/网络可达性），
            # 失败时必须能看到合流输出的真实内容才能定位
            pytest.fail(
                f"--json 2>&1 输出不是纯 JSON ({e}):\n"
                f"--- merged stdout+stderr repr ---\n{r.stdout!r}\n"
                f"--- returncode: {r.returncode} ---"
            )
        assert data["success"] is True
        assert "Saved note" not in r.stdout
