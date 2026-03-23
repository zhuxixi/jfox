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
            # 基础笔记操作
            "search_notes": self.search_notes,
            "add_note": self.add_note,
            "get_note": self.get_note,
            "list_notes": self.list_notes,
            "get_kb_info": self.get_kb_info,
            "find_related": self.find_related,
            
            # 知识库管理
            "kb_list": self.kb_list,
            "kb_switch": self.kb_switch,
            "kb_current": self.kb_current,
            
            # 引用关系查询
            "get_backlinks": self.get_backlinks,
            "get_graph_stats": self.get_graph_stats,
            "get_orphans": self.get_orphans,
            
            # 高级搜索
            "search_by_tag": self.search_by_tag,
            "daily_notes": self.daily_notes,
            "query_semantic_graph": self.query_semantic_graph,
            
            # 链接建议
            "suggest_links": self.suggest_links,
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
    
    # =========================================================================
    # 知识库管理接口
    # =========================================================================
    
    def kb_list(self) -> List[Dict[str, Any]]:
        """
        列出所有知识库
        
        Returns:
            知识库列表
        """
        from .global_config import get_global_config_manager
        
        manager = get_global_config_manager()
        all_kbs = manager.list_knowledge_bases()
        current_name = manager.get_default_kb_name()
        
        result = []
        for kb_entry in all_kbs:
            # 获取每个知识库的统计信息
            stats = self.kb_manager.get_info(kb_entry.name)
            result.append({
                "name": kb_entry.name,
                "path": kb_entry.path,
                "description": kb_entry.description or "",
                "total_notes": stats.total_notes if stats else 0,
                "is_current": kb_entry.name == current_name,
            })
        
        return result
    
    def kb_switch(self, name: str) -> Dict[str, Any]:
        """
        切换到指定知识库
        
        Args:
            name: 知识库名称
            
        Returns:
            切换结果
        """
        success, message = self.kb_manager.switch(name)
        return {
            "success": success,
            "message": message,
        }
    
    def kb_current(self) -> Dict[str, Any]:
        """
        获取当前知识库信息
        
        Returns:
            当前知识库详细信息
        """
        from .global_config import get_global_config_manager
        
        manager = get_global_config_manager()
        current_name = manager.get_default_kb_name()
        
        if not current_name:
            return {"error": "No default knowledge base configured"}
        
        stats = self.kb_manager.get_info(current_name)
        if not stats:
            return {"error": f"Knowledge base '{current_name}' not found"}
        
        return {
            "name": stats.name,
            "path": str(stats.path),
            "description": stats.description or "",
            "total_notes": stats.total_notes,
            "by_type": stats.by_type,
            "created": stats.created,
            "last_used": stats.last_used,
            "is_current": True,
        }
    
    # =========================================================================
    # 引用关系查询接口
    # =========================================================================
    
    def get_backlinks(self, note_id: str) -> List[Dict[str, Any]]:
        """
        获取笔记的反向链接
        
        Args:
            note_id: 笔记 ID
            
        Returns:
            反向链接列表
        """
        n = note_module.load_note_by_id(note_id)
        if not n:
            return []
        
        result = []
        for back_id in n.backlinks:
            back_note = note_module.load_note_by_id(back_id)
            if back_note:
                result.append({
                    "id": back_id,
                    "title": back_note.title,
                    "type": back_note.type.value,
                })
        
        return result
    
    def get_graph_stats(self) -> Dict[str, Any]:
        """
        获取知识图谱统计
        
        Returns:
            图谱统计信息
        """
        config = get_config()
        graph = KnowledgeGraph(config).build()
        stats = graph.get_stats()
        
        return {
            "total_nodes": stats.total_nodes,
            "total_edges": stats.total_edges,
            "avg_degree": round(stats.avg_degree, 2),
            "isolated_nodes": stats.isolated_nodes,
            "clusters": stats.clusters,
        }
    
    def get_orphans(self, limit: int = 20) -> List[Dict[str, Any]]:
        """
        获取孤立笔记（没有链接的笔记）
        
        Args:
            limit: 返回数量限制
            
        Returns:
            孤立笔记列表
        """
        config = get_config()
        graph = KnowledgeGraph(config).build()
        orphan_ids = graph.get_orphan_notes()
        
        result = []
        for oid in orphan_ids[:limit]:
            n = note_module.load_note_by_id(oid)
            if n:
                result.append({
                    "id": oid,
                    "title": n.title,
                    "type": n.type.value,
                })
        
        return result
    
    # =========================================================================
    # 高级搜索接口
    # =========================================================================
    
    def search_by_tag(self, tag: str, limit: int = 10) -> List[Dict[str, Any]]:
        """
        按标签搜索笔记
        
        Args:
            tag: 标签名称
            limit: 返回数量限制
            
        Returns:
            匹配的笔记列表
        """
        notes = note_module.list_notes(limit=1000)  # 获取较多笔记用于筛选
        
        result = []
        for n in notes:
            if tag.lower() in [t.lower() for t in n.tags]:
                result.append({
                    "id": n.id,
                    "title": n.title,
                    "type": n.type.value,
                    "tags": n.tags,
                    "created": n.created.isoformat() if n.created else None,
                })
                if len(result) >= limit:
                    break
        
        return result
    
    def daily_notes(self, date: Optional[str] = None) -> List[Dict[str, Any]]:
        """
        获取某天的笔记
        
        Args:
            date: 日期 (YYYY-MM-DD)，不传则返回今天的笔记
            
        Returns:
            当天的笔记列表
        """
        from datetime import datetime
        
        if date:
            target_date = datetime.strptime(date, "%Y-%m-%d")
        else:
            target_date = datetime.now()
        
        date_str = target_date.strftime("%Y%m%d")
        
        all_notes = note_module.list_notes()
        daily_notes = [n for n in all_notes if n.id.startswith(date_str)]
        
        return [
            {
                "id": n.id,
                "title": n.title,
                "type": n.type.value,
                "created": n.created.isoformat() if n.created else None,
            }
            for n in daily_notes
        ]
    
    def query_semantic_graph(
        self, 
        query: str, 
        top_k: int = 5, 
        graph_depth: int = 2
    ) -> List[Dict[str, Any]]:
        """
        语义+图谱联合查询
        
        Args:
            query: 搜索查询
            top_k: 语义搜索返回数量
            graph_depth: 图谱遍历深度
            
        Returns:
            增强的搜索结果
        """
        # 1. 语义搜索
        vector_results = note_module.search_notes(query, top_k=top_k)
        
        # 2. 构建知识图谱
        config = get_config()
        graph = KnowledgeGraph(config).build()
        
        # 3. 为每个结果添加图谱关联
        enriched_results = []
        for r in vector_results:
            note_id = r.get("id")
            related = graph.get_related(note_id, depth=graph_depth)
            
            # 获取相关笔记详情
            related_notes = []
            for depth_key, note_ids in related.items():
                depth = int(depth_key.split("_")[1])
                for nid in note_ids[:3]:  # 限制每层数量
                    n = note_module.load_note_by_id(nid)
                    if n:
                        related_notes.append({
                            "id": nid,
                            "title": n.title,
                            "type": n.type.value,
                            "depth": depth,
                        })
            
            enriched_results.append({
                "id": note_id,
                "title": r.get("metadata", {}).get("title", "Untitled"),
                "content": r.get("document", "")[:200] + "...",
                "type": r.get("metadata", {}).get("type", "unknown"),
                "score": r.get("score", 0),
                "related_notes": related_notes,
                "graph_neighbors": len(graph.get_neighbors(note_id)),
            })
        
        return enriched_results
    
    def suggest_links(
        self, 
        content: str, 
        top_k: int = 5, 
        threshold: float = 0.6
    ) -> List[Dict[str, Any]]:
        """
        根据内容推荐可以链接的已有笔记
        
        Args:
            content: 输入内容
            top_k: 返回建议数量
            threshold: 相似度阈值
            
        Returns:
            建议链接的笔记列表
        """
        from . import note as note_module
        
        suggestions = note_module.suggest_links(
            content=content,
            top_k=top_k,
            threshold=threshold
        )
        
        return suggestions


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
