"""
输出格式化器

支持多种输出格式：json, table, csv, yaml, paths, tree
"""

import csv
import io
import json
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

import yaml
from rich.console import Console
from rich.table import Table
from rich.tree import Tree


class OutputFormatter:
    """输出格式化器"""

    SUPPORTED_FORMATS = ["json", "table", "csv", "yaml", "paths", "tree"]

    @classmethod
    def format(cls, data: Any, format_type: str, **kwargs) -> str:
        """
        根据格式类型格式化数据

        Args:
            data: 要格式化的数据
            format_type: 格式类型
            **kwargs: 额外参数

        Returns:
            格式化后的字符串

        Raises:
            ValueError: 不支持的格式
        """
        format_type = format_type.lower()

        if format_type == "json":
            return cls.to_json(data)
        elif format_type == "table":
            return cls.to_table(data, **kwargs)
        elif format_type == "csv":
            return cls.to_csv(data, **kwargs)
        elif format_type == "yaml":
            return cls.to_yaml(data)
        elif format_type == "paths":
            return cls.to_paths(data)
        elif format_type == "tree":
            return cls.to_tree(data, **kwargs)
        else:
            raise ValueError(
                f"Unsupported format: {format_type}. "
                f"Supported: {', '.join(cls.SUPPORTED_FORMATS)}"
            )

    @staticmethod
    def to_json(data: Any) -> str:
        """
        JSON 格式

        Args:
            data: 任意可序列化数据

        Returns:
            JSON 字符串
        """
        return json.dumps(data, ensure_ascii=False, indent=2, default=str)

    @staticmethod
    def to_csv(data: List[Dict], headers: Optional[List[str]] = None) -> str:
        """
        CSV 格式

        Args:
            data: 字典列表
            headers: 自定义表头，None 则使用所有键

        Returns:
            CSV 字符串
        """
        if not data:
            return ""

        # 确定表头
        if headers is None:
            if isinstance(data[0], dict):
                headers = list(data[0].keys())
            else:
                return ""

        # 创建 CSV
        output = io.StringIO()
        writer = csv.DictWriter(
            output, fieldnames=headers, extrasaction="ignore", quoting=csv.QUOTE_MINIMAL
        )
        writer.writeheader()

        for row in data:
            if isinstance(row, dict):
                # 处理嵌套字典和列表
                flat_row = {}
                for key, value in row.items():
                    if isinstance(value, (list, dict)):
                        flat_row[key] = json.dumps(value, ensure_ascii=False)
                    else:
                        flat_row[key] = value
                writer.writerow(flat_row)

        return output.getvalue()

    @staticmethod
    def to_yaml(data: Any) -> str:
        """
        YAML 格式

        Args:
            data: 任意可序列化数据

        Returns:
            YAML 字符串
        """
        return yaml.dump(
            data, allow_unicode=True, sort_keys=False, default_flow_style=False, indent=2
        )

    @staticmethod
    def to_paths(data: Union[List[Dict], List[Path], List[str]], key: str = "filepath") -> str:
        """
        路径格式 - 每行一个路径

        Args:
            data: 数据列表
            key: 路径字段名

        Returns:
            路径字符串，每行一个
        """
        if not data:
            return ""

        paths = []
        for item in data:
            if isinstance(item, (str, Path)):
                paths.append(str(item))
            elif isinstance(item, dict):
                path = item.get(key)
                if path:
                    paths.append(str(path))

        return "\n".join(paths)

    @staticmethod
    def to_table(
        data: List[Dict], columns: Optional[List[str]] = None, title: Optional[str] = None
    ) -> str:
        """
        表格格式（使用 Rich）

        注意：此函数返回的字符串需要通过 rich.console 渲染

        Args:
            data: 字典列表
            columns: 显示的列，None 则显示所有
            title: 表格标题

        Returns:
            表格对象（特殊处理，需要渲染）
        """
        if not data:
            return "(No data)"

        # 确定列
        if columns is None:
            if isinstance(data[0], dict):
                columns = list(data[0].keys())
            else:
                return str(data)

        # 创建表格
        table = Table(title=title)
        for col in columns:
            table.add_column(str(col), overflow="fold")

        # 添加行
        for row in data:
            if isinstance(row, dict):
                values = []
                for col in columns:
                    val = row.get(col, "")
                    # 处理复杂类型
                    if isinstance(val, (list, dict)):
                        val = json.dumps(val, ensure_ascii=False)[:50]
                    elif isinstance(val, Path):
                        val = str(val)
                    values.append(str(val) if val is not None else "")
                table.add_row(*values)

        # 渲染为字符串
        console = Console(file=io.StringIO(), force_terminal=False)
        console.print(table)
        return console.file.getvalue()

    @staticmethod
    def to_tree(data: List[Dict], root_name: str = "notes", group_by: str = "type") -> str:
        """
        树形格式

        Args:
            data: 笔记数据列表
            root_name: 根节点名称
            group_by: 分组字段

        Returns:
            树形字符串
        """
        if not data:
            return f"{root_name}/"

        # 按类型分组
        groups: Dict[str, List[Dict]] = {}
        for item in data:
            if isinstance(item, dict):
                group_key = str(item.get(group_by, "unknown"))
                if group_key not in groups:
                    groups[group_key] = []
                groups[group_key].append(item)

        # 创建树
        tree = Tree(f"[bold]{root_name}/[/bold]")

        for group_name, items in sorted(groups.items()):
            group_node = tree.add(f"[cyan]{group_name}/[/cyan]")
            for item in items:
                title = item.get("title", "Untitled")
                note_id = item.get("id", "")
                if note_id:
                    group_node.add(f"{title} ([dim]{note_id}[/dim])")
                else:
                    group_node.add(title)

        # 渲染为字符串
        console = Console(file=io.StringIO(), force_terminal=False)
        console.print(tree)
        return console.file.getvalue()


def format_output(data: Any, format_type: str, console: Optional[Console] = None, **kwargs) -> None:
    """
    格式化并输出数据

    Args:
        data: 要格式化的数据
        format_type: 格式类型
        console: Rich console 实例，None 则创建新实例
        **kwargs: 额外参数传递给 formatter
    """
    if console is None:
        console = Console()

    if format_type == "table":
        # table 格式需要特殊处理
        output = OutputFormatter.to_table(data, **kwargs)
        if output == "(No data)":
            console.print(output)
        else:
            # 重新渲染表格（因为 to_table 已经返回了渲染后的字符串）
            console.print(output)
    elif format_type == "tree":
        output = OutputFormatter.to_tree(data, **kwargs)
        console.print(output)
    else:
        output = OutputFormatter.format(data, format_type, **kwargs)
        console.print(output)


# 向后兼容：支持 --json 参数
def is_json_format(json_flag: bool, format_param: Optional[str]) -> bool:
    """
    判断是否使用 JSON 格式（向后兼容）

    Args:
        json_flag: --json 标志
        format_param: --format 参数值

    Returns:
        是否使用 JSON 格式
    """
    if format_param:
        return format_param.lower() == "json"
    return json_flag
