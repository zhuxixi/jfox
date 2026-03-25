"""
Knowledge graph module using NetworkX for Zettelkasten notes.

Provides:
- Link graph construction from note relationships
- Backlink auto-generation
- Graph traversal and path finding
- Hub and authority analysis
"""

import os
import re
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple
from dataclasses import dataclass
from datetime import datetime

import networkx as nx
from rich.console import Console
from rich.table import Table

from .config import ZKConfig
from .models import Note, NoteType


console = Console()


@dataclass
class GraphStats:
    """Statistics for the knowledge graph."""
    total_nodes: int
    total_edges: int
    avg_degree: float
    isolated_nodes: int
    hubs: List[Tuple[str, int]]  # (note_id, degree) pairs
    clusters: int


class KnowledgeGraph:
    """
    Manages the knowledge graph for Zettelkasten notes.
    
    Uses NetworkX for graph operations and provides methods for:
    - Building graph from notes directory
    - Finding connections between notes
    - Analyzing graph structure
    """
    
    def __init__(self, config: ZKConfig):
        self.config = config
        self.graph = nx.DiGraph()
        self._note_cache: Dict[str, Note] = {}
    
    def build(self, force: bool = False) -> "KnowledgeGraph":
        """
        Build the knowledge graph from all notes.
        
        Args:
            force: If True, rebuild even if graph exists
            
        Returns:
            Self for chaining
        """
        if not force and len(self.graph) > 0:
            return self
        
        self.graph.clear()
        self._note_cache.clear()
        
        notes_dir = Path(self.config.notes_dir)
        if not notes_dir.exists():
            console.print("[yellow]Notes directory not found[/yellow]")
            return self
        
        # First pass: collect all notes
        for note_file in notes_dir.rglob("*.md"):
            try:
                note = self._parse_note_file(note_file)
                if note:
                    self._note_cache[note.id] = note
                    self.graph.add_node(
                        note.id,
                        title=note.title,
                        type=note.type.value,
                        tags=note.tags,
                        created=note.created.isoformat() if note.created else None,
                        modified=note.updated.isoformat() if note.updated else None
                    )
            except Exception as e:
                console.print(f"[red]Error parsing {note_file}: {e}[/red]")
        
        # Second pass: add edges from frontmatter links
        for note_id, note in self._note_cache.items():
            for linked_id in note.links:
                if linked_id in self._note_cache:
                    self.graph.add_edge(note_id, linked_id, type="links")
                    # Auto-generate backlink
                    self.graph.add_edge(linked_id, note_id, type="backlink")
        
        # Third pass: extract and add wiki links from content [[...]]
        for note_id, note in self._note_cache.items():
            wiki_links = self._extract_wiki_links(note.content)
            for link_text in wiki_links:
                linked_id = self._resolve_link(link_text)
                if linked_id and linked_id in self._note_cache:
                    # Add edge if not already exists
                    if not self.graph.has_edge(note_id, linked_id):
                        self.graph.add_edge(note_id, linked_id, type="wiki_link")
                        self.graph.add_edge(linked_id, note_id, type="backlink")
        
        return self
    
    def _extract_wiki_links(self, content: str) -> List[str]:
        """Extract [[...]] wiki links from content."""
        pattern = r'\[\[(.*?)\]\]'
        matches = re.findall(pattern, content)
        return [m.strip() for m in matches]
    
    def _resolve_link(self, link_text: str) -> Optional[str]:
        """Resolve a link text to a note ID."""
        # First try exact ID match
        if link_text in self._note_cache:
            return link_text
        
        # Then try title match
        for note_id, note in self._note_cache.items():
            if link_text.lower() in note.title.lower():
                return note_id
            if note.title.lower() == link_text.lower():
                return note_id
        
        return None
    
    def _parse_note_file(self, file_path: Path) -> Optional[Note]:
        """Parse a note file and extract metadata."""
        from .note import NoteManager
        return NoteManager.load_note(file_path)
    
    def get_neighbors(self, note_id: str, direction: str = "both") -> List[str]:
        """
        Get neighboring notes.
        
        Args:
            note_id: The note ID
            direction: "out" for outgoing, "in" for incoming, "both" for all
            
        Returns:
            List of neighboring note IDs
        """
        if note_id not in self.graph:
            return []
        
        neighbors = set()
        if direction in ("out", "both"):
            neighbors.update(self.graph.successors(note_id))
        if direction in ("in", "both"):
            neighbors.update(self.graph.predecessors(note_id))
        
        return list(neighbors)
    
    def get_path(self, source: str, target: str, max_length: int = 5) -> Optional[List[str]]:
        """
        Find shortest path between two notes.
        
        Args:
            source: Starting note ID
            target: Target note ID
            max_length: Maximum path length
            
        Returns:
            List of note IDs forming the path, or None if no path exists
        """
        try:
            path = nx.shortest_path(self.graph, source, target)
            if len(path) <= max_length + 1:
                return path
            return None
        except (nx.NetworkXNoPath, nx.NodeNotFound):
            return None
    
    def get_related(self, note_id: str, depth: int = 2) -> Dict[str, List[str]]:
        """
        Get related notes at various depths.
        
        Args:
            note_id: Starting note ID
            depth: How many hops to traverse
            
        Returns:
            Dictionary mapping depth to list of note IDs
        """
        if note_id not in self.graph:
            return {}
        
        related: Dict[str, List[str]] = {}
        seen = {note_id}
        current_level = {note_id}
        
        for d in range(1, depth + 1):
            next_level = set()
            for node in current_level:
                neighbors = set(self.graph.successors(node)) | set(self.graph.predecessors(node))
                neighbors -= seen
                next_level.update(neighbors)
                seen.update(neighbors)
            
            if next_level:
                related[f"depth_{d}"] = list(next_level)
                current_level = next_level
            else:
                break
        
        return related
    
    def find_clusters(self) -> List[Set[str]]:
        """Find clusters of strongly connected notes."""
        clusters = list(nx.strongly_connected_components(self.graph))
        # Filter out singletons and sort by size
        clusters = [c for c in clusters if len(c) > 1]
        clusters.sort(key=len, reverse=True)
        return clusters
    
    def get_hubs(self, top_n: int = 10) -> List[Tuple[str, int]]:
        """
        Get the most connected notes (hubs).
        
        Args:
            top_n: Number of top hubs to return
            
        Returns:
            List of (note_id, degree) tuples
        """
        degrees = [(n, self.graph.degree(n)) for n in self.graph.nodes()]
        degrees.sort(key=lambda x: x[1], reverse=True)
        return degrees[:top_n]
    
    def get_stats(self) -> GraphStats:
        """Get comprehensive graph statistics."""
        if len(self.graph) == 0:
            return GraphStats(0, 0, 0, 0, [], 0)
        
        total_nodes = len(self.graph)
        total_edges = self.graph.number_of_edges()
        avg_degree = sum(d for _, d in self.graph.degree()) / total_nodes if total_nodes > 0 else 0
        isolated = len(list(nx.isolates(self.graph)))
        hubs = self.get_hubs(10)
        clusters = len(self.find_clusters())
        
        return GraphStats(
            total_nodes=total_nodes,
            total_edges=total_edges,
            avg_degree=avg_degree,
            isolated_nodes=isolated,
            hubs=hubs,
            clusters=clusters
        )
    
    def visualize_text(self, note_id: Optional[str] = None, depth: int = 2) -> str:
        """
        Generate text-based visualization of the graph or subgraph.
        
        Args:
            note_id: If provided, show subgraph around this note
            depth: Depth of subgraph to show
            
        Returns:
            ASCII visualization string
        """
        if note_id and note_id in self.graph:
            nodes = {note_id}
            current = {note_id}
            for _ in range(depth):
                next_level = set()
                for n in current:
                    next_level.update(self.graph.successors(n))
                    next_level.update(self.graph.predecessors(n))
                nodes.update(next_level)
                current = next_level
            
            subgraph = self.graph.subgraph(nodes)
        else:
            subgraph = self.graph
        
        lines = []
        lines.append(f"Graph: {len(subgraph)} nodes, {subgraph.number_of_edges()} edges")
        lines.append("")
        
        for node in subgraph.nodes():
            title = subgraph.nodes[node].get("title", "Untitled")
            lines.append(f"📄 {node}: {title}")
            
            successors = list(subgraph.successors(node))
            predecessors = list(subgraph.predecessors(node))
            
            if successors:
                links_str = ", ".join(successors[:5])
                if len(successors) > 5:
                    links_str += f" (+{len(successors) - 5} more)"
                lines.append(f"   → Links to: {links_str}")
            
            if predecessors:
                backlinks_str = ", ".join(predecessors[:5])
                if len(predecessors) > 5:
                    backlinks_str += f" (+{len(predecessors) - 5} more)"
                lines.append(f"   ← Backlinks: {backlinks_str}")
            
            if successors or predecessors:
                lines.append("")
        
        return "\n".join(lines)
    
    def get_orphan_notes(self) -> List[str]:
        """Get notes with no links (orphans)."""
        return [n for n in self.graph.nodes() if self.graph.degree(n) == 0]
    
    def get_broken_links(self) -> Dict[str, List[str]]:
        """Find notes that link to non-existent notes."""
        broken = {}
        for node in self.graph.nodes():
            if node in self._note_cache:
                for link in self._note_cache[node].links:
                    if link not in self._note_cache:
                        if node not in broken:
                            broken[node] = []
                        broken[node].append(link)
        return broken
