"""
Kimi Skill MCP Server

提供 MCP (Model Context Protocol) 接口，让 Kimi AI 可以操作知识库
"""

import json
import logging
from typing import Any, Dict, List, Optional
from pathlib import Path

from .kb_manager import get_kb_manager
from . import note as note_module
from .graph import KnowledgeGraph
from .config import get_config


logger = logging.getLogger(__name__)


class ZKMCPHandler:
    """
    MCP 请求处理器
    
    处理 Kimi 发来的 MCP 请求
    """
    
    def __init__(self):
        self.kb_manager = get_kb_manager()
    
    def handle(self, request: Dict[str, Any]) -> Dict[str, Any]:
        """
        处理 MCP 请求
        
        Args:
            request: MCP 请求对象
            
        Returns:
            MCP 响应对象
        """
        method = request.get("method")
        params = request.get("params", {})
        
        handlers = {
            "search_notes": self.search_notes,
            "add_note": self.add_note,
            "get_note": self.get_note,
            "list_notes": self.list_notes,
            "get_kb_info": self.get_kb_info,
            "find_related": self.find_related,
        }
        
        handler = handlers.get(method)
        if handler:
            try:
                result = handler(**params)
                return {
                    "jsonrpc": "2.0",
                    "id": request.get("id"),
                    "result": result
                }
            except Exception as e:
                logger.error(f"Error handling {method}: {e}")
                return {
                    "jsonrpc": "2.0",
                    "id": request.get("id"),
                    "error": {"code": -32000, "message": str(e)}
                }
        else:
            return {
                "jsonrpc": "2.0",
                "id": request.get("id"),
                "error": {"code": -32601, "message": f"Method not found: {method}"}
            }
    
    def search_notes(self, query: str, top_k: int = 5) -> List[Dict[str, Any]]:
        """
        搜索笔记
        
        Args:
            query: 搜索查询
            top_k: 返回结果数量
            
        Returns:
            笔记列表
        """
        results = note_module.search_notes(query, top_k=top_k)
        
        # 简化结果
        simplified = []
        for r in results:
            simplified.append({
                "id": r.get("id"),
                "title": r.get("metadata", {}).get("title", "Untitled"),
                "content": r.get("document", "")[:200] + "...",
                "type": r.get("metadata", {}).get("type", "unknown"),
                "score": r.get("score", 0),
            })
        
        return simplified
    
    def add_note(
        self, 
        content: str, 
        title: Optional[str] = None,
        note_type: str = "fleeting",
        tags: Optional[List[str]] = None
    ) -> Dict[str, Any]:
        """
        添加笔记
        
        Args:
            content: 笔记内容
            title: 标题
            note_type: 类型
            tags: 标签
            
        Returns:
            创建的笔记信息
        """
        from .models import NoteType
        
        nt = NoteType(note_type.lower())
        new_note = note_module.create_note(
            content=content,
            title=title,
            note_type=nt,
            tags=tags or []
        )
        
        if note_module.save_note(new_note):
            return {
                "id": new_note.id,
                "title": new_note.title,
                "type": new_note.type.value,
                "filepath": str(new_note.filepath),
            }
        else:
            raise Exception("Failed to save note")
    
    def get_note(self, note_id: str) -> Optional[Dict[str, Any]]:
        """
        获取笔记详情
        
        Args:
            note_id: 笔记 ID
            
        Returns:
            笔记详情
        """
        n = note_module.load_note_by_id(note_id)
        if not n:
            return None
        
        return {
            "id": n.id,
            "title": n.title,
            "content": n.content,
            "type": n.type.value,
            "tags": n.tags,
            "links": n.links,
            "backlinks": n.backlinks,
            "created": n.created.isoformat() if n.created else None,
        }
    
    def list_notes(
        self, 
        note_type: Optional[str] = None, 
        limit: int = 10
    ) -> List[Dict[str, Any]]:
        """
        列出笔记
        
        Args:
            note_type: 笔记类型筛选
            limit: 数量限制
            
        Returns:
            笔记列表
        """
        from .models import NoteType
        
        nt = None
        if note_type:
            nt = NoteType(note_type.lower())
        
        notes = note_module.list_notes(note_type=nt, limit=limit)
        
        return [
            {
                "id": n.id,
                "title": n.title,
                "type": n.type.value,
                "created": n.created.isoformat() if n.created else None,
            }
            for n in notes
        ]
    
    def get_kb_info(self) -> Dict[str, Any]:
        """
        获取知识库信息
        
        Returns:
            知识库统计信息
        """
        stats = self.kb_manager.get_current_kb_info()
        if not stats:
            return {"error": "No knowledge base found"}
        
        return {
            "name": stats.name,
            "path": str(stats.path),
            "total_notes": stats.total_notes,
            "by_type": stats.by_type,
            "is_current": stats.is_current,
        }
    
    def find_related(self, note_id: str, depth: int = 2) -> List[Dict[str, Any]]:
        """
        查找相关笔记
        
        Args:
            note_id: 起始笔记 ID
            depth: 遍历深度
            
        Returns:
            相关笔记列表
        """
        config = get_config()
        graph = KnowledgeGraph(config).build()
        
        related = graph.get_related(note_id, depth=depth)
        
        result = []
        for depth_key, note_ids in related.items():
            depth_num = int(depth_key.split("_")[1])
            for nid in note_ids:
                n = note_module.load_note_by_id(nid)
                if n:
                    result.append({
                        "id": nid,
                        "title": n.title,
                        "type": n.type.value,
                        "depth": depth_num,
                    })
        
        return result


class ZKMCPServer:
    """
    MCP Server
    
    提供 STDIO 或 HTTP 接口
    """
    
    def __init__(self):
        self.handler = ZKMCPHandler()
    
    def run_stdio(self):
        """
        运行 STDIO 模式（用于 Kimi Skill）
        
        读取 stdin 的 JSON-RPC 请求，写入 stdout
        """
        import sys
        
        logger.info("MCP Server started (stdio mode)")
        
        while True:
            try:
                # 读取一行
                line = sys.stdin.readline()
                if not line:
                    break
                
                line = line.strip()
                if not line:
                    continue
                
                # 解析请求
                request = json.loads(line)
                
                # 处理请求
                response = self.handler.handle(request)
                
                # 输出响应
                print(json.dumps(response, ensure_ascii=False), flush=True)
                
            except json.JSONDecodeError as e:
                logger.error(f"Invalid JSON: {e}")
                print(json.dumps({
                    "jsonrpc": "2.0",
                    "error": {"code": -32700, "message": "Parse error"}
                }), flush=True)
            except Exception as e:
                logger.error(f"Error: {e}")
                print(json.dumps({
                    "jsonrpc": "2.0",
                    "error": {"code": -32603, "message": str(e)}
                }), flush=True)
