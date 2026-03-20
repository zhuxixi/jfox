"""
CLI 命令封装

提供易于使用的 Python API 来调用 zk 命令
"""

import json
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, List, Dict, Any, Union


@dataclass
class CLIResult:
    """CLI 命令执行结果"""
    success: bool
    returncode: int
    stdout: str
    stderr: str
    data: Optional[Dict[str, Any]] = None
    
    @property
    def output(self) -> str:
        """获取标准输出"""
        return self.stdout
    
    def json(self) -> Optional[Dict[str, Any]]:
        """解析 JSON 输出"""
        return self.data


class ZKCLI:
    """
    ZK CLI 封装
    
    提供 Python API 调用 CLI 命令
    
    用法:
        cli = ZKCLI(kb_path)
        result = cli.add("内容", title="标题")
        assert result.success
    """
    
    def __init__(self, kb_path: Optional[Path] = None):
        """
        初始化 CLI 封装
        
        Args:
            kb_path: 知识库路径（None 使用当前默认）
        """
        self.kb_path = kb_path
        self._last_result: Optional[CLIResult] = None
    
    def _run(
        self, 
        cmd: str, 
        *args, 
        capture_output: bool = True,
        json_output: bool = True
    ) -> CLIResult:
        """
        运行 CLI 命令
        
        Args:
            cmd: 子命令
            *args: 参数
            capture_output: 是否捕获输出
            json_output: 是否使用 JSON 输出
            
        Returns:
            CLIResult
        """
        # 构建命令
        command = ["python", "-m", "zk", cmd]
        
        # 添加其他参数（先添加，让 --path 在后面覆盖）
        command.extend(args)
        
        # 如果指定了知识库路径，使用 --path（init 命令支持 --path）
        if self.kb_path is not None and cmd == "init":
            if "--path" not in args:
                command.extend(["--path", str(self.kb_path)])
        
        # 默认使用 JSON 输出（便于解析）
        if json_output and "--json" not in args and "--no-json" not in args:
            command.append("--json")
        
        # 运行命令
        result = subprocess.run(
            command,
            capture_output=capture_output,
            text=True,
            cwd=str(Path(__file__).parent.parent.parent)
        )
        
        # 解析输出
        data = None
        if json_output and result.stdout:
            stdout = result.stdout.strip()
            try:
                data = json.loads(stdout)
            except json.JSONDecodeError:
                # 如果失败，可能是日志混在输出中，尝试提取 JSON 部分
                import re
                json_match = re.search(r'\{.*\}', stdout, re.DOTALL)
                if json_match:
                    try:
                        data = json.loads(json_match.group())
                    except json.JSONDecodeError:
                        pass
        
        success = result.returncode == 0
        
        cli_result = CLIResult(
            success=success,
            returncode=result.returncode,
            stdout=result.stdout,
            stderr=result.stderr,
            data=data
        )
        
        self._last_result = cli_result
        return cli_result
    
    # ==================== 基础命令 ====================
    
    def init(self) -> CLIResult:
        """初始化知识库"""
        return self._run("init")
    
    def add(
        self, 
        content: str, 
        title: Optional[str] = None,
        note_type: Optional[str] = None,
        tags: Optional[List[str]] = None,
        source: Optional[str] = None
    ) -> CLIResult:
        """
        添加笔记
        
        Args:
            content: 笔记内容
            title: 标题
            note_type: 类型 (fleeting/literature/permanent)
            tags: 标签列表
            source: 来源
        """
        args = [content]
        
        if title:
            args.extend(["--title", title])
        
        if note_type:
            args.extend(["--type", note_type])
        
        if tags:
            for tag in tags:
                args.extend(["--tag", tag])
        
        if source:
            args.extend(["--source", source])
        
        return self._run("add", *args)
    
    def list(self, note_type: Optional[str] = None, limit: Optional[int] = None) -> CLIResult:
        """列出笔记"""
        args = []
        if note_type:
            args.extend(["--type", note_type])
        if limit:
            args.extend(["--limit", str(limit)])
        
        return self._run("list", *args)
    
    def search(self, query: str, top: int = 5, note_type: Optional[str] = None) -> CLIResult:
        """语义搜索"""
        args = [query, "--top", str(top)]
        if note_type:
            args.extend(["--type", note_type])
        
        return self._run("search", *args)
    
    def delete(self, note_id: str, force: bool = False) -> CLIResult:
        """删除笔记"""
        args = [note_id]
        if force:
            args.append("--force")
        
        return self._run("delete", *args)
    
    def status(self) -> CLIResult:
        """查看知识库状态"""
        return self._run("status")
    
    # ==================== 链接相关 ====================
    
    def refs(
        self, 
        note_id: Optional[str] = None, 
        search: Optional[str] = None
    ) -> CLIResult:
        """查看引用关系"""
        args = []
        if note_id:
            args.extend(["--note", note_id])
        if search:
            args.extend(["--search", search])
        
        return self._run("refs", *args)
    
    # ==================== 图谱相关 ====================
    
    def graph_stats(self) -> CLIResult:
        """查看图谱统计"""
        return self._run("graph", "--stats")
    
    def graph_orphans(self) -> CLIResult:
        """查看孤立笔记"""
        return self._run("graph", "--orphans")
    
    # ==================== 索引相关 ====================
    
    def index_status(self) -> CLIResult:
        """查看索引状态"""
        return self._run("index", "status")
    
    def index_rebuild(self) -> CLIResult:
        """重建索引"""
        return self._run("index", "rebuild")
    
    def index_verify(self) -> CLIResult:
        """验证索引"""
        return self._run("index", "verify")
    
    # ==================== 知识库管理 ====================
    
    def kb_list(self) -> CLIResult:
        """列出知识库"""
        return self._run("kb", "list")
    
    def kb_create(
        self, 
        name: str, 
        path: Optional[Path] = None,
        description: Optional[str] = None
    ) -> CLIResult:
        """创建知识库"""
        args = ["create", name]
        if path:
            args.extend(["--path", str(path)])
        if description:
            args.extend(["--desc", description])
        
        return self._run("kb", *args)
    
    def kb_switch(self, name: str) -> CLIResult:
        """切换知识库"""
        return self._run("kb", "switch", name)
    
    def kb_remove(self, name: str, force: bool = False) -> CLIResult:
        """删除知识库"""
        args = ["remove", name]
        if force:
            args.append("--force")
        
        return self._run("kb", *args)
    
    def kb_info(self, name: Optional[str] = None) -> CLIResult:
        """查看知识库详情"""
        args = ["info"]
        if name:
            args.append(name)
        
        return self._run("kb", *args)
