"""git_extractor 单元测试"""

import textwrap
from pathlib import Path

from jfox.git_extractor import parse_git_log_output


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