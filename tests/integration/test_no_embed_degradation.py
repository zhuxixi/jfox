"""#519 no-embed 集成测试（A4/A5/A6/A7/A10）。

必须在无 sentence-transformers 环境执行（CI Fast job 天然满足；
本地用 .venv-noembed/bin/python -m pytest 运行）。

命名注意：conftest 的 pytest_collection_modifyitems 会给 nodeid 含
"embedding"/"semantic"/"vector" 的测试自动加 embedding 标记（CI Fast
按 `not embedding` 过滤会整组 deselect），类名/用例名必须避开这些词。
"""

import os

import pytest

from jfox.embedding_backend import is_local_embed_available

# 隔离真实 daemon：开发机可能运行着用户的 embedding daemon，子进程 add 会经
# HTTP 成功编码（如 bge-m3 1024 维），破坏「零语义基础设施」场景。
# JFOX_DAEMON_PROCESS 是既有守卫（_check_daemon：daemon 进程内不外连），
# 设定后编码路径只走本地 → 无 sentence-transformers 即确定性地缺失；
# 子进程经环境继承同样生效。
os.environ["JFOX_DAEMON_PROCESS"] = "1"

pytestmark = [
    pytest.mark.no_embed,
    pytest.mark.integration,
    pytest.mark.skipif(
        is_local_embed_available(), reason="需在无 sentence-transformers 环境执行 (#519)"
    ),
]


def _kb_store(kb_path):
    """按 KB 路径直接构造 VectorStore。

    不走 use_kb/全局注册表：测试进程内的 GlobalConfigManager 单例可能早于
    CLI 子进程的 init 注册而创建，缓存陈旧快照导致 not found（#519 实测）。
    """
    from jfox.config import ZKConfig
    from jfox.vector_store import VectorStore

    cfg = ZKConfig(base_dir=kb_path)
    store = VectorStore(persist_directory=cfg.chroma_dir)
    store.init()
    return store


def _seed_index_row(kb_path, note_id):
    """直接经 ChromaDB 预置 dummy 向量行（不经 embedding，模拟既有索引）。"""
    store = _kb_store(kb_path)
    store.collection.add(
        ids=[note_id],
        embeddings=[[0.1] * 8],
        documents=["既有向量行"],
        metadatas=[{"title": "t", "type": "fleeting", "filepath": "x", "tags": ""}],
    )


def _get_indexed_ids(kb_path, note_id):
    store = _kb_store(kb_path)
    return store.collection.get(ids=[note_id])["ids"]


class TestAddDegradation:  # A4
    def test_add_creates_note_bm25_skips_index(self, cli):
        result = cli.add("轻量安装降级测试内容", title="轻量安装")
        assert result.returncode == 0
        data = result.json()
        assert data["success"] is True
        # 提示出现且含安装指引
        assert "semantic_index_warning" in data
        assert "UV_TORCH_BACKEND" in data["semantic_index_warning"]
        # BM25 可检索到
        search = cli._run("search", "轻量安装", "--mode", "keyword")
        assert search.returncode == 0
        assert search.json()["total"] >= 1
        # 语义写入未发生（collection 为空）
        store = _kb_store(cli.kb_path)
        assert store.collection.count() == 0


class TestEditPreservesIndexRow:  # A4 行保留
    def test_edit_keeps_existing_row(self, cli):
        created = cli.add("编辑前内容", title="编辑测试")
        note_id = created.json()["note"]["id"]
        _seed_index_row(cli.kb_path, note_id)

        edited = cli._run("edit", note_id, "--content", "编辑后内容轻量")
        assert edited.returncode == 0
        assert "semantic_index_warning" in edited.json()

        assert _get_indexed_ids(cli.kb_path, note_id) == [note_id]  # 行未被删除
