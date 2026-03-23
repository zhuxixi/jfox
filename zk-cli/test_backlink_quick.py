#!/usr/bin/env python3
"""
快速验证反向链接功能（不使用 pytest，直接调用 Python API）
"""

import sys
from pathlib import Path

# 添加项目路径
sys.path.insert(0, str(Path(__file__).parent))

from tests.utils.temp_kb import temp_knowledge_base
from tests.utils.zk_cli import ZKCLI


def test_backlink():
    """快速测试反向链接"""
    print("=" * 50)
    print("反向链接功能快速验证")
    print("=" * 50)
    
    with temp_knowledge_base() as kb_path:
        print(f"\n1. 创建临时知识库: {kb_path}")
        cli = ZKCLI(kb_path)
        
        # 初始化
        print("\n2. 初始化知识库...")
        result = cli.init()
        if not result.success:
            print(f"   ❌ 初始化失败: {result.stderr}")
            return False
        print("   ✓ 初始化成功")
        
        # 创建目标笔记
        print("\n3. 创建目标笔记 (Note A)...")
        target = cli.add("Content of Note A", title="Note A", note_type="permanent")
        if not target.success:
            print(f"   ❌ 创建失败: {target.stderr}")
            return False
        target_id = target.data["note"]["id"]
        print(f"   ✓ 目标笔记创建成功, ID: {target_id}")
        
        # 创建源笔记，链接到目标
        print("\n4. 创建源笔记 (Note B)，链接到 Note A...")
        source = cli.add("Content of Note B referencing [[Note A]]", title="Note B", note_type="permanent")
        if not source.success:
            print(f"   ❌ 创建失败: {source.stderr}")
            return False
        source_id = source.data["note"]["id"]
        print(f"   ✓ 源笔记创建成功, ID: {source_id}")
        
        # 验证正向链接
        print("\n5. 验证正向链接 (Note B -> Note A)...")
        refs = cli.refs(note_id=source_id)
        forward_links = [l["id"] for l in refs.data.get("forward_links", [])]
        if target_id in forward_links:
            print("   ✓ 正向链接正确")
        else:
            print(f"   ❌ 正向链接缺失: {forward_links}")
            return False
        
        # 验证反向链接
        print("\n6. 验证反向链接 (Note A <- Note B)...")
        refs = cli.refs(note_id=target_id)
        back_links = [l["id"] for l in refs.data.get("backward_links", [])]
        if source_id in back_links:
            print("   ✓ 反向链接正确")
        else:
            print(f"   ❌ 反向链接缺失: {back_links}")
            return False
        
        # 清理
        print("\n7. 清理知识库...")
        cli.cleanup()
        print("   ✓ 清理完成")
        
        print("\n" + "=" * 50)
        print("✅ 所有测试通过！反向链接功能正常")
        print("=" * 50)
        return True


if __name__ == "__main__":
    try:
        success = test_backlink()
        sys.exit(0 if success else 1)
    except Exception as e:
        print(f"\n❌ 测试异常: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
