#!/usr/bin/env python3
"""
验证反向链接功能（最小化测试，只验证核心逻辑）
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))

from tests.utils.temp_kb import temp_knowledge_base
from tests.utils.zk_cli import ZKCLI

def main():
    print("验证反向链接自动维护功能...")
    print("=" * 50)
    
    with temp_knowledge_base() as kb_path:
        cli = ZKCLI(kb_path)
        cli.init()
        
        # 创建 Note A
        print("\n1. 创建 Note A...")
        note_a = cli.add("Content A", title="Note A", note_type="permanent")
        assert note_a.success, f"失败: {note_a.stderr}"
        id_a = note_a.data["note"]["id"]
        print(f"   ✓ Note A ID: {id_a}")
        
        # 创建 Note B 链接到 A
        print("\n2. 创建 Note B，链接到 Note A...")
        note_b = cli.add("Content B referencing [[Note A]]", title="Note B", note_type="permanent")
        assert note_b.success, f"失败: {note_b.stderr}"
        id_b = note_b.data["note"]["id"]
        print(f"   ✓ Note B ID: {id_b}")
        
        # 验证正向链接
        print("\n3. 验证正向链接 (B -> A)...")
        refs_b = cli.refs(note_id=id_b)
        forward = [l["id"] for l in refs_b.data.get("forward_links", [])]
        assert id_a in forward, f"正向链接缺失: {forward}"
        print("   ✓ 正向链接正确")
        
        # 验证反向链接（核心功能）
        print("\n4. 验证反向链接 (A <- B)...")
        refs_a = cli.refs(note_id=id_a)
        backward = [l["id"] for l in refs_a.data.get("backward_links", [])]
        assert id_b in backward, f"反向链接缺失: {backward}"
        print("   ✓ 反向链接正确！")
        
        cli.cleanup()
        
    print("\n" + "=" * 50)
    print("✅ 反向链接功能验证通过！")
    print("=" * 50)
    return 0

if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as e:
        print(f"\n❌ 验证失败: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
