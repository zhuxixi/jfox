"""
测试类型: 单元测试
目标模块: jfox.cli (check 命令)
预估耗时: < 1秒
依赖要求: 无外部依赖
"""

from contextlib import contextmanager
from unittest.mock import MagicMock, patch

import pytest
from typer.testing import CliRunner

pytestmark = [pytest.mark.unit, pytest.mark.fast]

from jfox.cli import app

runner = CliRunner()


@contextmanager
def _setup_temp_kb(temp_kb):
    """设置临时知识库目录并 mock use_kb 上下文管理器"""
    from jfox.config import ZKConfig, config

    cfg = ZKConfig(base_dir=temp_kb)
    cfg.ensure_dirs()

    original_base_dir = config.base_dir
    original_notes_dir = config.notes_dir
    original_zk_dir = config.zk_dir
    original_chroma_dir = config.chroma_dir

    # 直接切换 config 到临时知识库
    config.base_dir = temp_kb
    config.notes_dir = cfg.notes_dir
    config.zk_dir = cfg.zk_dir
    config.chroma_dir = cfg.chroma_dir

    try:
        with patch("jfox.config.use_kb") as mock_use_kb:
            mock_use_kb.return_value.__enter__ = MagicMock(return_value=None)
            mock_use_kb.return_value.__exit__ = MagicMock(return_value=False)
            yield cfg
    finally:
        # 恢复原始配置
        config.base_dir = original_base_dir
        config.notes_dir = original_notes_dir
        config.zk_dir = original_zk_dir
        config.chroma_dir = original_chroma_dir


class TestCheckCommand:
    """jfox check 命令测试"""

    def test_check_clean_kb(self, temp_kb):
        """干净知识库返回无问题"""
        with _setup_temp_kb(temp_kb):
            result = runner.invoke(app, ["check"])
            assert result.exit_code == 0
            assert "No issues found" in result.output or "clean" in result.output.lower()

    def test_check_detects_empty_file(self, temp_kb):
        """检测空文件"""
        with _setup_temp_kb(temp_kb) as cfg:
            empty_file = cfg.notes_dir / "permanent" / "empty.md"
            empty_file.write_text("", encoding="utf-8")

            result = runner.invoke(app, ["check"])
            assert result.exit_code == 1
            assert "empty" in result.output.lower()
            assert "empty.md" in result.output

    def test_check_detects_corrupt_file(self, temp_kb):
        """检测损坏文件（无 frontmatter）"""
        with _setup_temp_kb(temp_kb) as cfg:
            corrupt_file = cfg.notes_dir / "fleeting" / "corrupt.md"
            corrupt_file.write_text("This is not valid markdown for jfox", encoding="utf-8")

            result = runner.invoke(app, ["check"])
            assert result.exit_code == 1
            assert "corrupt" in result.output.lower()
            assert "corrupt.md" in result.output

    def test_check_json_output(self, temp_kb):
        """JSON 格式输出"""
        import json

        with _setup_temp_kb(temp_kb) as cfg:
            empty_file = cfg.notes_dir / "permanent" / "empty.md"
            empty_file.write_text("", encoding="utf-8")

            result = runner.invoke(app, ["check", "--format", "json"])
            assert result.exit_code == 1
            data = json.loads(result.output)
            assert data["total"] == 1
            assert data["issues"][0]["issue"] == "empty"
            assert data["issues"][0]["size"] == 0

    def test_check_clean_deletes_empty(self, temp_kb):
        """--clean 删除空文件后退出码为 0"""
        with _setup_temp_kb(temp_kb) as cfg:
            empty_file = cfg.notes_dir / "permanent" / "empty.md"
            empty_file.write_text("", encoding="utf-8")

            result = runner.invoke(app, ["check", "--clean"], input="y\n")
            assert "Deleted" in result.output or "deleted" in result.output.lower()
            assert not empty_file.exists()
            assert result.exit_code == 0

    def test_check_clean_keeps_corrupt(self, temp_kb):
        """--clean 不删除损坏但非空的文件，退出码为 1"""
        with _setup_temp_kb(temp_kb) as cfg:
            corrupt_file = cfg.notes_dir / "fleeting" / "corrupt.md"
            corrupt_file.write_text("Some content without frontmatter", encoding="utf-8")

            result = runner.invoke(app, ["check", "--clean"])
            assert corrupt_file.exists()
            assert "corrupt" in result.output.lower()
            assert result.exit_code == 1
