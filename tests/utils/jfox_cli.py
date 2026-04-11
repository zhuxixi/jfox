"""
CLI 命令封装

提供易于使用的 Python API 来调用 jfox 命令
"""

import json
import os
import subprocess
import sys
import uuid
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
        cli.init()  # 初始化并注册知识库
        result = cli.add("内容", title="标题")
        assert result.success
        cli.cleanup()  # 清理时注销知识库
    """
    
    def __init__(self, kb_path: Optional[Path] = None, kb_name: Optional[str] = None):
        """
        初始化 CLI 封装
        
        Args:
            kb_path: 知识库路径（None 使用当前默认）
            kb_name: 知识库名称（None 自动生成）
        """
        self.kb_path = kb_path
        self.kb_name = kb_name or f"test_{uuid.uuid4().hex[:8]}"
        self._last_result: Optional[CLIResult] = None
        self._initialized = False
    
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
        command = [sys.executable, "-m", "jfox", cmd]
        
        # 添加其他参数
        command.extend(args)
        
        # 如果指定了知识库路径，使用 --path（init 命令支持 --path）
        if self.kb_path is not None and cmd == "init":
            if "--path" not in args:
                command.extend(["--path", str(self.kb_path)])
            # 使用指定的名称
            if "--name" not in args:
                command.extend(["--name", self.kb_name])
        
        # 对于非 init/kb 命令，如果有知识库名称，使用 --kb
        if cmd not in ("init", "kb") and self._initialized:
            if "--kb" not in args and "-k" not in args:
                command.extend(["--kb", self.kb_name])
        
        # 默认使用 JSON 输出（便于解析）
        if json_output and "--json" not in args and "--no-json" not in args:
            command.append("--json")
        
        # 运行命令
        env = {**os.environ, "PYTHONUTF8": "1"}
        result = subprocess.run(
            command,
            capture_output=capture_output,
            text=True,
            encoding="utf-8",
            cwd=str(Path(__file__).parent.parent.parent),
            env=env,
        )
        
        # 解析输出
        data = None
        if json_output and result.stdout:
            stdout = result.stdout.strip()
            try:
                data = json.loads(stdout)
            except json.JSONDecodeError:
                # 如果失败，可能是日志混在输出中，尝试提取 JSON 部分
                # 策略：从开头找第一个 '{'，从结尾找最后一个 '}'
                import re
                # 尝试匹配最外层的大括号（考虑嵌套）
                start_idx = stdout.find('{')
                if start_idx != -1:
                    # 找到匹配的结束括号
                    brace_count = 0
                    end_idx = start_idx
                    for i, char in enumerate(stdout[start_idx:], start=start_idx):
                        if char == '{':
                            brace_count += 1
                        elif char == '}':
                            brace_count -= 1
                            if brace_count == 0:
                                end_idx = i + 1
                                break
                    
                    if brace_count == 0 and end_idx > start_idx:
                        json_str = stdout[start_idx:end_idx]
                        try:
                            data = json.loads(json_str)
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
        """初始化知识库并注册"""
        result = self._run("init")
        if result.success:
            self._initialized = True
        return result
    
    def cleanup(self) -> CLIResult:
        """清理并注销知识库"""
        if self._initialized:
            # 注销知识库
            result = self._run("kb", "remove", self.kb_name, "--force")
            self._initialized = False
            return result
        return CLIResult(success=True, returncode=0, stdout="", stderr="", data={})
    
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

    def edit(
        self,
        note_id: str,
        content: Optional[str] = None,
        title: Optional[str] = None,
        tags: Optional[List[str]] = None,
        note_type: Optional[str] = None,
        source: Optional[str] = None,
    ) -> CLIResult:
        """
        编辑笔记

        Args:
            note_id: 笔记 ID
            content: 新内容
            title: 新标题
            tags: 新标签列表（替换全部）
            note_type: 新类型 (fleeting/literature/permanent)
            source: 新来源
        """
        args = [note_id]
        if content:
            args.extend(["--content", content])
        if title:
            args.extend(["--title", title])
        if tags:
            for tag in tags:
                args.extend(["--tag", tag])
        if note_type:
            args.extend(["--type", note_type])
        if source:
            args.extend(["--source", source])

        return self._run("edit", *args)

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
    
    def kb_current(self, json_output: bool = True) -> CLIResult:
        """查看当前知识库"""
        args = ["current"]
        if not json_output:
            args.extend(["--format", "table"])
        
        return self._run("kb", *args, json_output=json_output)
    
    # ==================== 通用命令执行 ====================
    
    def run(self, cmd: str, *args) -> CLIResult:
        """
        运行任意 CLI 命令
        
        用于测试 --format 等参数
        
        Args:
            cmd: 子命令
            *args: 参数
            
        Returns:
            CLIResult
        """
        # 检测是否需要 JSON 解析
        json_output = "--json" not in args and "--format" not in args
        return self._run(cmd, *args, json_output=json_output)
    
    # ==================== 工作流命令 ====================
    
    def daily(self, date: Optional[str] = None) -> CLIResult:
        """
        查看某天的笔记（默认今天）
        
        Args:
            date: 日期 (YYYY-MM-DD, 默认今天)
        """
        args = []
        if date:
            args.extend(["--date", date])
        
        return self._run("daily", *args)
    
    def inbox(self, limit: int = 20) -> CLIResult:
        """
        查看临时笔记 (Fleeting Notes)
        
        Args:
            limit: 显示数量
        """
        args = ["--limit", str(limit)]
        return self._run("inbox", *args)
    
    def query(
        self, 
        query_str: str, 
        top: int = 5, 
        graph_depth: int = 2
    ) -> CLIResult:
        """
        语义搜索 + 知识图谱联合查询
        
        Args:
            query_str: 搜索查询
            top: 返回结果数量
            graph_depth: 图谱遍历深度
        """
        args = [query_str, "--top", str(top), "--depth", str(graph_depth)]
        return self._run("query", *args)
    
    def suggest_links(
        self, 
        content: str, 
        top_k: int = 5, 
        threshold: float = 0.6
    ) -> CLIResult:
        """
        根据内容推荐可以链接的已有笔记
        
        Args:
            content: 内容文本
            top_k: 返回建议数量
            threshold: 相似度阈值 (0-1)
        """
        args = [content, "--top", str(top_k), "--threshold", str(threshold)]
        return self._run("suggest-links", *args)
