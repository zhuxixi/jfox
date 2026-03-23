"""Tests for template functionality"""
import pytest
import tempfile
from pathlib import Path

from zk.template import (
    TemplateManager,
    NoteTemplate,
    TemplateNotFoundError,
    TemplateRenderError,
)


class TestTemplateManager:
    """Test TemplateManager functionality"""
    
    @pytest.fixture
    def temp_templates_dir(self):
        """Create temporary templates directory"""
        with tempfile.TemporaryDirectory() as tmpdir:
            yield Path(tmpdir)
    
    @pytest.fixture
    def template_manager(self, temp_templates_dir):
        """Create template manager instance"""
        return TemplateManager(temp_templates_dir)
    
    def test_creates_templates_directory(self, temp_templates_dir):
        """Test that templates directory is created"""
        manager = TemplateManager(temp_templates_dir)
        assert temp_templates_dir.exists()
    
    def test_creates_builtin_templates(self, template_manager):
        """Test that built-in templates are created"""
        templates = template_manager.list_templates()
        template_names = [t.name for t in templates]
        
        assert "quick" in template_names
        assert "meeting" in template_names
        assert "literature" in template_names
    
    def test_get_template_existing(self, template_manager):
        """Test getting an existing template"""
        template = template_manager.get_template("quick")
        
        assert template is not None
        assert template.name == "quick"
        assert template.note_type == "fleeting"
        assert "{{date}}" in template.title_format
    
    def test_get_template_nonexistent(self, template_manager):
        """Test getting a non-existent template"""
        template = template_manager.get_template("nonexistent")
        assert template is None
    
    def test_render_quick_template(self, template_manager):
        """Test rendering quick template"""
        result = template_manager.render(
            "quick",
            {"title": "Test Note", "content": "Test content"}
        )
        
        assert "Test Note" in result["title"]
        assert "Test content" in result["content"]
        assert result["note_type"] == "fleeting"
        assert "fleeting" in result["tags"]
    
    def test_render_meeting_template(self, template_manager):
        """Test rendering meeting template"""
        result = template_manager.render(
            "meeting",
            {"title": "Weekly Meeting", "content": "Discussion"}
        )
        
        assert "Weekly Meeting" in result["title"]
        assert "Discussion" in result["content"]
        assert result["note_type"] == "permanent"
        assert "meeting" in result["tags"]
        assert "{{date}}" not in result["content"]  # Should be rendered
    
    def test_render_literature_template(self, template_manager):
        """Test rendering literature template"""
        result = template_manager.render(
            "literature",
            {
                "title": "Clean Code",
                "content": "Summary",
                "source": "Book"
            }
        )
        
        assert result["title"] == "Clean Code"
        assert "Summary" in result["content"]
        assert "Book" in result["content"]
        assert result["note_type"] == "literature"
    
    def test_render_template_not_found(self, template_manager):
        """Test rendering a non-existent template raises error"""
        with pytest.raises(TemplateNotFoundError) as exc_info:
            template_manager.render("nonexistent", {})
        
        assert "nonexistent" in str(exc_info.value)
        assert "quick" in str(exc_info.value)  # Should list available templates
    
    def test_default_variables_are_provided(self, template_manager):
        """Test that default variables (date, time) are provided"""
        result = template_manager.render(
            "quick",
            {"title": "Test", "content": "Content"}
        )
        
        # Should have today's date in title
        from datetime import datetime
        today = datetime.now().strftime("%Y-%m-%d")
        assert today in result["title"]
    
    def test_available_templates_list(self, template_manager):
        """Test getting list of available template names"""
        names = template_manager.get_available_templates()
        
        assert "quick" in names
        assert "meeting" in names
        assert "literature" in names
    
    def test_builtin_templates_are_marked(self, template_manager):
        """Test that built-in templates are marked correctly"""
        templates = template_manager.list_templates()
        
        for template in templates:
            assert template.is_builtin is True


class TestNoteTemplate:
    """Test NoteTemplate dataclass"""
    
    def test_template_creation(self):
        """Test creating a NoteTemplate"""
        template = NoteTemplate(
            name="test",
            description="Test template",
            note_type="fleeting",
            title_format="{{date}}-{{title}}",
            content="Test content",
            tags=["tag1", "tag2"],
        )
        
        assert template.name == "test"
        assert template.description == "Test template"
        assert template.tags == ["tag1", "tag2"]
