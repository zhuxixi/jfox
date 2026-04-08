"""
Integration Test Suite for ZK CLI

Run with: pytest tests/test_integration.py -v
"""

import pytest
import json
from pathlib import Path


class TestBasicCRUD:
    """Basic CRUD tests"""
    
    def test_init_creates_directory_structure(self, temp_kb):
        """Test init creates correct directory structure"""
        from utils.jfox_cli import ZKCLI
        
        cli = ZKCLI(temp_kb)
        result = cli.init()
        
        assert result.success
        assert (temp_kb / "notes" / "fleeting").exists()
        assert (temp_kb / "notes" / "permanent").exists()
    
    def test_kb_operations(self, cli):
        """Test knowledge base operations"""
        # Test kb list
        result = cli.kb_list()
        assert result.success
        
        # Parse stdout manually since logging interferes
        data = json.loads(result.stdout)
        assert "knowledge_bases" in data


class TestWikiLinks:
    """Bidirectional linking tests"""
    
    def test_add_with_wiki_link(self, cli):
        """Test wiki link creation"""
        # Create target note
        cli.add("ML basics content", title="ML Basics", note_type="permanent")
        
        # Create note with link
        result = cli.add(
            "Deep learning uses [[ML Basics]] concepts",
            title="Deep Learning",
            note_type="permanent"
        )
        
        assert result.success


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
