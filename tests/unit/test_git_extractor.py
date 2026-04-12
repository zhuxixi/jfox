"""git_extractor 单元测试"""

import textwrap
from unittest.mock import MagicMock, patch

import pytest

from jfox.git_extractor import commits_to_notes, extract_commits, parse_git_log_output


class TestParseGitLogOutput:
    """测试 git log 输出解析"""

    def test_single_commit(self):
        """解析单条 commit"""
        raw = textwrap.dedent("""\
            ---COMMIT_START---
            Hash: abc123def456
            Subject: feat: add login
            Author: 张三
            Date: 2026-04-10

            实现了登录功能
        """)
        result = parse_git_log_output(raw)
        assert len(result) == 1
        assert result[0]["hash"] == "abc123def456"
        assert result[0]["subject"] == "feat: add login"
        assert result[0]["author"] == "张三"
        assert result[0]["date"] == "2026-04-10"
        assert result[0]["body"] == "实现了登录功能"

    def test_multiple_commits(self):
        """解析多条 commit"""
        raw = textwrap.dedent("""\
            ---COMMIT_START---
            Hash: aaa111
            Subject: first commit
            Author: Alice
            Date: 2026-04-01

            body of first
            ---COMMIT_START---
            Hash: bbb222
            Subject: second commit
            Author: Bob
            Date: 2026-04-02

            body of second
        """)
        result = parse_git_log_output(raw)
        assert len(result) == 2
        assert result[0]["hash"] == "aaa111"
        assert result[1]["hash"] == "bbb222"

    def test_empty_body(self):
        """空 body 的 commit"""
        raw = textwrap.dedent("""\
            ---COMMIT_START---
            Hash: abc123
            Subject: chore: version bump
            Author: Bot
            Date: 2026-04-10
        """)
        result = parse_git_log_output(raw)
        assert len(result) == 1
        assert result[0]["body"] == ""

    def test_body_with_special_chars(self):
        """body 包含特殊字符（|、中文、换行）"""
        raw = textwrap.dedent("""\
            ---COMMIT_START---
            Hash: abc123
            Subject: fix: parser | handling
            Author: 张三
            Date: 2026-04-10

            修复 | 分隔符问题
            和中文内容
            Co-Authored-By: Claude <noreply@anthropic.com>
        """)
        result = parse_git_log_output(raw)
        assert len(result) == 1
        assert "|" in result[0]["body"]
        assert "中文" in result[0]["body"]

    def test_empty_input(self):
        """空输入返回空列表"""
        result = parse_git_log_output("")
        assert result == []

    def test_multiline_body_preserved(self):
        """多行 body 完整保留"""
        raw = textwrap.dedent("""\
            ---COMMIT_START---
            Hash: abc123
            Subject: feat: big change
            Author: Alice
            Date: 2026-04-10

            line 1
            line 2
            line 3
        """)
        result = parse_git_log_output(raw)
        assert result[0]["body"] == "line 1\nline 2\nline 3"

    def test_delimiter_in_body_ignored(self):
        """commit body 包含分隔符文本不应产生幻影 commit"""
        raw = textwrap.dedent("""\
            ---COMMIT_START---
            Hash: abc123
            Subject: feat: something
            Author: Alice
            Date: 2026-04-10

            ---COMMIT_START--- this is just body text
        """)
        result = parse_git_log_output(raw)
        assert len(result) == 1


class TestExtractCommits:
    """测试 git 仓库 commit 提取"""

    @patch("jfox.git_extractor.subprocess.run")
    def test_basic_extraction(self, mock_run):
        """基本提取流程"""
        mock_run.return_value = MagicMock(
            returncode=0,
            stdout="---COMMIT_START---\nHash: abc123\nSubject: feat: test\nAuthor: Alice\nDate: 2026-04-10\n\nbody\n",
        )
        result = extract_commits("/fake/repo", limit=10)
        assert len(result) == 1
        assert result[0]["hash"] == "abc123"
        assert result[0]["subject"] == "feat: test"
        call_args = mock_run.call_args
        assert call_args[1]["encoding"] == "utf-8"
        assert call_args[1]["errors"] == "replace"

    @patch("jfox.git_extractor.subprocess.run")
    def test_path_normalization(self, mock_run):
        """路径规范化（resolve 处理）"""
        mock_run.return_value = MagicMock(returncode=0, stdout="")
        extract_commits("/c/Users/test/repo")
        called_cmd = mock_run.call_args[0][0]
        assert "-C" in called_cmd

    @patch("jfox.git_extractor.subprocess.run")
    def test_git_not_repo_error(self, mock_run):
        """非 git 仓库应抛出 ValueError"""
        mock_run.return_value = MagicMock(
            returncode=128,
            stderr="fatal: not a git repository",
        )
        with pytest.raises(ValueError, match="not a git repository"):
            extract_commits("/not/a/repo")

    @patch("jfox.git_extractor.subprocess.run")
    def test_default_limit_50(self, mock_run):
        """默认 limit 为 50"""
        mock_run.return_value = MagicMock(returncode=0, stdout="")
        extract_commits("/fake/repo")
        called_cmd = mock_run.call_args[0][0]
        assert "-50" in called_cmd


class TestCommitsToNotes:
    """测试 commit → note 转换"""

    def test_basic_conversion(self):
        """基本转换"""
        commits = [
            {
                "hash": "abc123def456",
                "subject": "feat: add login",
                "author": "张三",
                "date": "2026-04-10",
                "body": "实现了 JWT 认证",
            }
        ]
        result = commits_to_notes(commits, repo_name="my-app")
        assert len(result) == 1
        assert result[0]["title"] == "feat: add login"
        assert "abc123d" in result[0]["content"]
        assert "张三" in result[0]["content"]
        assert "2026-04-10" in result[0]["content"]
        assert "JWT" in result[0]["content"]
        assert "source:my-app" in result[0]["tags"]
        assert "source:git-log" in result[0]["tags"]

    def test_empty_commits(self):
        """空列表返回空列表"""
        result = commits_to_notes([], repo_name="test")
        assert result == []

    def test_long_hash_truncated(self):
        """hash 截断为短 hash"""
        commits = [
            {
                "hash": "a" * 40,
                "subject": "test",
                "author": "A",
                "date": "2026-01-01",
                "body": "",
            }
        ]
        result = commits_to_notes(commits, repo_name="test")
        assert "a" * 7 in result[0]["content"]

    def test_body_with_co_authored_by_stripped(self):
        """body 末尾的 Co-authored-by 行被清理"""
        commits = [
            {
                "hash": "abc1234",
                "subject": "feat: something",
                "author": "Alice",
                "date": "2026-04-10",
                "body": "real content\n\nCo-authored-by: Bob <bob@example.com>\nCo-authored-by: Claude <noreply@anthropic.com>",
            }
        ]
        result = commits_to_notes(commits, repo_name="test")
        assert "real content" in result[0]["content"]
        assert "Co-authored-by" not in result[0]["content"]

    def test_repo_name_from_path(self):
        """repo_name=None 时从路径提取目录名"""
        commits = [
            {"hash": "abc1234", "subject": "test", "author": "A", "date": "2026-01-01", "body": ""}
        ]
        result = commits_to_notes(commits, repo_path="/home/user/my-project")
        assert "source:my-project" in result[0]["tags"]


class TestIngestLogCommand:
    """测试 ingest-log CLI 命令"""

    @patch("jfox.performance.bulk_import_notes")
    @patch("jfox.git_extractor.extract_commits")
    def test_ingest_log_basic(self, mock_extract, mock_import, tmp_path):
        """基本 ingest-log 流程"""
        mock_extract.return_value = [
            {
                "hash": "abc123def456",
                "subject": "feat: test feature",
                "author": "Alice",
                "date": "2026-04-10",
                "body": "test body",
            }
        ]
        mock_import.return_value = {"imported": 1, "failed": 0, "total": 1}

        from typer.testing import CliRunner

        from jfox.cli import app

        runner = CliRunner()
        result = runner.invoke(app, ["ingest-log", str(tmp_path)], catch_exceptions=False)

        assert result.exit_code == 0
        mock_extract.assert_called_once()
        mock_import.assert_called_once()

        # 验证传入 bulk_import 的 notes 格式
        notes_data = mock_import.call_args[1]["notes_data"]
        assert len(notes_data) == 1
        assert notes_data[0]["title"] == "feat: test feature"
        assert "abc123d" in notes_data[0]["content"]

    @patch("jfox.performance.bulk_import_notes")
    @patch("jfox.git_extractor.extract_commits")
    def test_ingest_log_empty_repo(self, mock_extract, mock_import, tmp_path):
        """空仓库不导入，bulk_import_notes 不应被调用"""
        mock_extract.return_value = []

        from typer.testing import CliRunner

        from jfox.cli import app

        runner = CliRunner()
        result = runner.invoke(app, ["ingest-log", str(tmp_path)], catch_exceptions=False)

        assert result.exit_code == 0
        mock_import.assert_not_called()
