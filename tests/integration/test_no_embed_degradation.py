"""#519 no-embed 集成测试（A4/A5/A6/A7/A10）。

必须在无 sentence-transformers 环境执行（CI Fast job 天然满足；
本地用 .venv-noembed/bin/python -m pytest 运行）。

命名注意：conftest 的 pytest_collection_modifyitems 会先把 nodeid **lower()** 再做
大小写不敏感子串匹配（类名也算！），CI Fast 按 `not embedding and not slow`
过滤会把命中项整组 deselect，类名/用例名必须避开以下全部子串：
- "embedding"/"semantic"/"vector" → embedding + very_slow
- "search"/"suggest"/"query" → slow
- "bulk"/"batch"/"large"/"many" → slow + bulk
（实测：类名 TestSearchModes 因含 "search" 被整类 slow——大写也无济于事）
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


class TestDegradeProtocols:  # A5（类名避开 conftest 陷阱：原 TestSearchModes 含 "search" 被整类 slow）
    # 命名避开 conftest 自动标记关键词（embedding/semantic/vector/search/suggest/query）

    def test_hybrid_degrades_to_bm25_with_warning(self, cli):
        cli.add("混合检索降级测试量子内容", title="混合降级")
        result = cli._run("search", "量子", "--mode", "hybrid")
        assert result.returncode == 0
        data = result.json()
        assert data["total"] >= 1
        assert data["warnings"][0]["code"] == "embedding_unavailable"
        assert data["warnings"][0]["fallback"] == "keyword"

    def test_explicit_mode_refused(self, cli):
        # 显式语义模式：服务不可用 → 拒绝而非静默降级（原计划名 test_semantic_mode_refused
        # 因 conftest 自动标记陷阱改此名）
        result = cli._run("search", "量子", "--mode", "semantic")
        assert result.returncode == 1
        data = result.json()
        assert data["code"] == "embed_dependency_missing"
        assert "UV_TORCH_BACKEND" in data["error"]

    def test_keyword_mode_unaffected(self, cli):
        cli.add("关键词模式不受影响内容", title="关键词模式")
        result = cli._run("search", "不受影响", "--mode", "keyword")
        assert result.returncode == 0
        assert result.json()["total"] >= 1
        assert "warnings" not in result.json()

    def test_joint_lookup_degrades_with_effective_mode(self, cli):
        # 原 plan 名 test_query_degrades_with_effective_mode：nodeid 含 "query" 会命中
        # conftest 规则二（自动 slow）被 CI Fast deselect，故改名（"joint lookup" 同义）
        cli.add("联合查询降级测试内容", title="联合查询")
        result = cli._run("query", "联合查询")
        assert result.returncode == 0
        data = result.json()
        assert data["effective_mode"] == "keyword"
        assert data["warnings"][0]["code"] == "embedding_unavailable"

    def test_link_hints_degrade_to_keyword(self, cli):
        # _suggest_links_impl 变更代码的唯一直接覆盖（tests/test_suggest_links.py 全组
        # 被 conftest 规则二自动 slow，CI Fast 不可见）
        cli.add("量子纠缠与拓扑序的关联笔记", title="量子纠缠")
        result = cli.suggest_links("量子纠缠")
        assert result.returncode == 0
        data = result.json()
        assert data["warnings"][0]["code"] == "embedding_unavailable"
        keyword_hits = [s for s in data["suggestions"] if s["match_type"] == "keyword"]
        assert len(keyword_hits) >= 1


class TestIndexRebuild:  # A6
    # 命名避开 conftest 陷阱：原 plan 名 test_rebuild_bm25_only_preserves_vectors 含 "vectors"

    def test_rebuild_bm25_only_keeps_existing_rows(self, cli):
        n1 = cli.add("重建保留测试甲", title="重建甲").json()["note"]["id"]
        n2 = cli.add("重建保留测试乙", title="重建乙").json()["note"]["id"]
        _seed_index_row(cli.kb_path, n1)
        _seed_index_row(cli.kb_path, n2)

        result = cli._run("index", "rebuild")
        assert result.returncode == 0
        data = result.json()
        assert data["semantic_skipped"] is True
        assert data["warnings"][0]["code"] == "embedding_unavailable"
        assert data["warnings"][0]["fallback"] == "bm25_only"
        assert data["bm25_rebuilt"] is True
        # 既有向量行保留（rebuild 不得清空 collection）
        assert _get_indexed_ids(cli.kb_path, n1) == [n1]
        assert _get_indexed_ids(cli.kb_path, n2) == [n2]
        # BM25 全量可检索
        keyword = cli._run("search", "重建甲", "--mode", "keyword")
        assert keyword.returncode == 0
        assert keyword.json()["total"] >= 1

    def test_rebuild_backlinks_still_works(self, cli):
        result = cli._run("index", "rebuild", "--backlinks")
        assert result.returncode == 0
        assert "backlinks_rebuilt" in result.json()
