"""#577 edit --json 链接字段契约文档静态防漂移测试（#601 自 test_json_schema_contract_doc.py 拆分）。"""

from pathlib import Path

import pytest

pytestmark = [pytest.mark.unit, pytest.mark.fast]

REPO_ROOT = Path(__file__).resolve().parents[3]
DOC = REPO_ROOT / "docs" / "json-schemas.md"


def test_edit_link_fields_documented():
    text = DOC.read_text(encoding="utf-8")
    assert "note{id,title,type,filepath,links,backlinks}" in text
    assert "`links_added[], links_removed[]`（恒有，可为空数组）" in text
