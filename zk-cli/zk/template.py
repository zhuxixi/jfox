"""Template management for standardized note creation"""

from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml
from jinja2 import Template, UndefinedError

from .models import NoteType


@dataclass
class NoteTemplate:
    """Template definition for creating notes"""
    name: str
    description: str
    note_type: str
    title_format: str
    content: str
    tags: List[str] = field(default_factory=list)
    is_builtin: bool = False


class TemplateError(Exception):
    """Template-related error"""
    pass


class TemplateNotFoundError(TemplateError):
    """Template not found error"""
    pass


class TemplateRenderError(TemplateError):
    """Template rendering error"""
    pass


class TemplateManager:
    """Manage note templates"""
    
    # Built-in template definitions
    BUILTIN_TEMPLATES = {
        "quick": {
            "name": "quick",
            "description": "快速记录想法",
            "note_type": "fleeting",
            "title_format": "{{date}}-{{title}}",
            "content": '## 快速笔记\n\n创建于 {{datetime}}\n\n{{content}}',
            "tags": ["fleeting"],
        },
        "meeting": {
            "name": "meeting",
            "description": "会议记录模板",
            "note_type": "permanent",
            "title_format": "{{date}}-{{title}}",
            "content": '## 会议信息\n- **日期**: {{date}}\n- **时间**: {{time}}\n\n## 参会人员\n\n## 议程\n\n## 会议内容\n\n{{content}}\n\n## 行动项\n- [ ] ',
            "tags": ["meeting", "permanent"],
        },
        "literature": {
            "name": "literature",
            "description": "阅读笔记模板",
            "note_type": "literature",
            "title_format": "{{title}}",
            "content": '## 文献信息\n- **来源**: {{source}}\n- **作者**: \n- **阅读日期**: {{date}}\n\n## 核心观点\n\n## 个人思考\n\n## 关联笔记\n\n{{content}}',
            "tags": ["literature"],
        },
    }
    
    def __init__(self, templates_dir: Path):
        """
        Initialize template manager
        
        Args:
            templates_dir: Directory to store templates
        """
        self.templates_dir = templates_dir
        self._ensure_templates_dir()
        self._ensure_builtin_templates()
    
    def _ensure_templates_dir(self) -> None:
        """Create templates directory if it doesn't exist"""
        self.templates_dir.mkdir(parents=True, exist_ok=True)
    
    def _ensure_builtin_templates(self) -> None:
        """Create built-in templates if they don't exist"""
        for name, template_data in self.BUILTIN_TEMPLATES.items():
            template_path = self.templates_dir / f"{name}.yaml"
            if not template_path.exists():
                self._save_template_file(template_path, template_data, is_builtin=True)
    
    def _save_template_file(self, path: Path, data: Dict[str, Any], is_builtin: bool = False) -> None:
        """Save template to YAML file"""
        template_data = {
            "name": data["name"],
            "description": data["description"],
            "note_type": data["note_type"],
            "title_format": data["title_format"],
            "content": data["content"],
            "tags": data.get("tags", []),
            "is_builtin": is_builtin,
        }
        with open(path, "w", encoding="utf-8") as f:
            yaml.dump(template_data, f, allow_unicode=True, sort_keys=False)
    
    def list_templates(self) -> List[NoteTemplate]:
        """
        List all available templates
        
        Returns:
            List of NoteTemplate objects
        """
        templates = []
        
        # Scan templates directory for YAML files
        for template_file in self.templates_dir.glob("*.yaml"):
            try:
                template = self._load_template_file(template_file)
                if template:
                    templates.append(template)
            except Exception:
                # Skip invalid template files
                continue
        
        # Sort by name
        templates.sort(key=lambda t: t.name)
        return templates
    
    def _load_template_file(self, path: Path) -> Optional[NoteTemplate]:
        """Load a single template from file"""
        with open(path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)
        
        if not data:
            return None
        
        return NoteTemplate(
            name=data.get("name", path.stem),
            description=data.get("description", ""),
            note_type=data.get("note_type", "fleeting"),
            title_format=data.get("title_format", "{{title}}"),
            content=data.get("content", ""),
            tags=data.get("tags", []),
            is_builtin=data.get("is_builtin", False),
        )
    
    def get_template(self, name: str) -> Optional[NoteTemplate]:
        """
        Get a template by name
        
        Args:
            name: Template name
            
        Returns:
            NoteTemplate or None if not found
        """
        template_path = self.templates_dir / f"{name}.yaml"
        
        if not template_path.exists():
            return None
        
        return self._load_template_file(template_path)
    
    def render(self, name: str, variables: Dict[str, Any]) -> Dict[str, Any]:
        """
        Render a template with variables
        
        Args:
            name: Template name
            variables: Variables to use in rendering
            
        Returns:
            Dict with rendered title, content, note_type, and tags
            
        Raises:
            TemplateNotFoundError: If template doesn't exist
            TemplateRenderError: If template rendering fails
        """
        template = self.get_template(name)
        
        if not template:
            available = [t.name for t in self.list_templates()]
            raise TemplateNotFoundError(
                f"Template '{name}' not found. "
                f"Available templates: {', '.join(available) if available else 'none'}"
            )
        
        # Merge provided variables with defaults
        render_vars = self._get_default_variables()
        render_vars.update(variables)
        
        try:
            # Render title
            title_template = Template(template.title_format)
            rendered_title = title_template.render(**render_vars)
            
            # Render content
            content_template = Template(template.content)
            rendered_content = content_template.render(**render_vars)
            
        except UndefinedError as e:
            raise TemplateRenderError(f"Template variable undefined: {e}")
        except Exception as e:
            raise TemplateRenderError(f"Failed to render template: {e}")
        
        return {
            "title": rendered_title,
            "content": rendered_content,
            "note_type": template.note_type,
            "tags": template.tags.copy(),
        }
    
    def _get_default_variables(self) -> Dict[str, str]:
        """Get default template variables (date, time, etc.)"""
        now = datetime.now()
        return {
            "date": now.strftime("%Y-%m-%d"),
            "time": now.strftime("%H:%M"),
            "datetime": now.strftime("%Y-%m-%d %H:%M"),
        }
    
    def get_available_templates(self) -> List[str]:
        """Get list of available template names"""
        return [t.name for t in self.list_templates()]
