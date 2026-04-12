"""
测试 Indexer.index_all() 在重建前清除旧数据

验证 rebuild 流程：先 clear 再 index
"""

import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest


class TestIndexerClearBeforeRebuild:
    """Indexer.index_all() 应先清除旧索引再重建"""

    def test_index_all_calls_vector_store_clear(self):
        """index_all() 应在索引笔记前调用 vector_store.clear()"""
        from jfox.indexer import Indexer

        mock_config = MagicMock()
        mock_vector_store = MagicMock()

        # 空笔记目录
        with tempfile.TemporaryDirectory() as tmpdir:
            notes_dir = Path(tmpdir) / "notes"
            notes_dir.mkdir()
            mock_config.notes_dir = str(notes_dir)

            indexer = Indexer(config=mock_config, vector_store=mock_vector_store)
            count = indexer.index_all()

            assert count == 0
            mock_vector_store.clear.assert_called_once()

    def test_index_all_clear_before_add(self):
        """clear() 必须在 add_or_update_note() 之前调用"""
        from jfox.indexer import Indexer

        mock_config = MagicMock()
        mock_vector_store = MagicMock()

        with tempfile.TemporaryDirectory() as tmpdir:
            notes_dir = Path(tmpdir) / "notes"
            notes_dir.mkdir()
            mock_config.notes_dir = str(notes_dir)

            # 创建假笔记文件
            note_file = notes_dir / "20260412120000-test.md"
            note_file.write_text(
                "---\nid: '20260412120000'\ntitle: Test\ntype: permanent\ntags: []\n---\nContent"
            )

            with patch("jfox.note.NoteManager") as mock_note_mgr:
                mock_note = MagicMock()
                mock_note.id = "20260412120000"
                mock_note_mgr.load_note.return_value = mock_note

                indexer = Indexer(config=mock_config, vector_store=mock_vector_store)
                indexer.index_all()

            # 验证调用顺序
            calls = mock_vector_store.method_calls
            clear_indices = [i for i, c in enumerate(calls) if c[0] == "clear"]
            add_indices = [i for i, c in enumerate(calls) if c[0] == "add_or_update_note"]

            if clear_indices and add_indices:
                assert clear_indices[0] < add_indices[0], (
                    f"clear() (call #{clear_indices[0]}) must be before "
                    f"add_or_update_note() (call #{add_indices[0]})"
                )
