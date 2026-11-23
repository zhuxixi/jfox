"""#363 status backend 契约文档静态防漂移测试（#601 自 test_json_schema_contract_doc.py 拆分）。"""

from pathlib import Path

import pytest

pytestmark = [pytest.mark.unit, pytest.mark.fast]

REPO_ROOT = Path(__file__).resolve().parents[3]
DOC = REPO_ROOT / "docs" / "json-schemas.md"


def test_status_backend_documents_source_field():
    """#363：status 的 backend 块新增 source 字段，文档必须跟上。"""
    text = DOC.read_text(encoding="utf-8")
    assert "backend{type,model,dimension,source}" in text


def test_status_dimension_nullability_in_breaking_changes():
    """#363：dimension 从 int 变 int|null，属破坏性变更，必须在表里登记。"""
    text = DOC.read_text(encoding="utf-8")
    assert "`backend.dimension` 可为 `null`" in text
