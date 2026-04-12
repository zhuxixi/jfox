"""
File system indexer with watchdog for auto-indexing Zettelkasten notes.

Provides:
- Real-time file monitoring
- Automatic indexing on file changes
- Batch indexing for initial setup
- Index status and statistics
"""

import threading
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Callable, Dict, List, Optional

from rich.console import Console
from rich.progress import Progress, SpinnerColumn, TextColumn
from watchdog.events import FileSystemEventHandler
from watchdog.observers import Observer

from .config import ZKConfig
from .vector_store import VectorStore

console = Console()


@dataclass
class IndexStats:
    """Statistics for the indexer."""

    total_indexed: int = 0
    last_indexed: Optional[datetime] = None
    pending_changes: int = 0
    errors: List[str] = field(default_factory=list)


class NoteEventHandler(FileSystemEventHandler):
    """
    Handles file system events for note files.

    Debounces rapid file changes and batches indexing operations.
    """

    def __init__(
        self,
        vector_store: VectorStore,
        config: ZKConfig,
        debounce_seconds: float = 1.0,
        callback: Optional[Callable[[str, str], None]] = None,
    ):
        self.vector_store = vector_store
        self.config = config
        self.debounce_seconds = debounce_seconds
        self.callback = callback

        self._pending: Dict[str, float] = {}
        self._lock = threading.Lock()
        self._timer: Optional[threading.Timer] = None
        self.stats = IndexStats()

    def on_modified(self, event):
        if event.is_directory:
            return
        if not event.src_path.endswith(".md"):
            return

        with self._lock:
            self._pending[event.src_path] = time.time()
            self._schedule_process()

    on_created = on_modified  # Treat creation same as modification

    def on_deleted(self, event):
        if event.is_directory:
            return
        if not event.src_path.endswith(".md"):
            return

        # Remove from vector store
        note_id = Path(event.src_path).stem
        try:
            self.vector_store.delete_note(note_id)
            if self.callback:
                self.callback("deleted", note_id)
        except Exception as e:
            self.stats.errors.append(f"Failed to delete {note_id}: {e}")

    def _schedule_process(self):
        """Schedule processing of pending changes."""
        if self._timer:
            self._timer.cancel()

        self._timer = threading.Timer(self.debounce_seconds, self._process_pending)
        self._timer.daemon = True
        self._timer.start()

    def _process_pending(self):
        """Process all pending file changes."""
        with self._lock:
            now = time.time()
            ready = [
                path
                for path, timestamp in self._pending.items()
                if now - timestamp >= self.debounce_seconds
            ]

            for path in ready:
                del self._pending[path]

            self.stats.pending_changes = len(self._pending)

        for path in ready:
            self._index_file(path)

    def _index_file(self, file_path: str):
        """Index a single note file."""
        from .note import NoteManager

        try:
            note = NoteManager.load_note(Path(file_path))
            if not note:
                return

            # Index in vector store
            self.vector_store.add_or_update_note(note)

            self.stats.total_indexed += 1
            self.stats.last_indexed = datetime.now()

            if self.callback:
                self.callback("indexed", note.id)

        except Exception as e:
            error_msg = f"Failed to index {file_path}: {e}"
            self.stats.errors.append(error_msg)
            if self.callback:
                self.callback("error", error_msg)


class Indexer:
    """
    Manages file system monitoring and indexing for Zettelkasten notes.

    Usage:
        indexer = Indexer(config, vector_store)
        indexer.start()  # Start watching
        ...
        indexer.stop()   # Stop watching
    """

    def __init__(self, config: ZKConfig, vector_store: VectorStore, debounce_seconds: float = 1.0):
        self.config = config
        self.vector_store = vector_store
        self.debounce_seconds = debounce_seconds

        self._observer: Optional[Observer] = None
        self._handler: Optional[NoteEventHandler] = None
        self._running = False

    def start(self, callback: Optional[Callable[[str, str], None]] = None):
        """
        Start the file system observer.

        Args:
            callback: Optional callback for events (event_type, message)
        """
        if self._running:
            return

        notes_dir = Path(self.config.notes_dir)
        if not notes_dir.exists():
            console.print(f"[yellow]Notes directory not found: {notes_dir}[/yellow]")
            return

        self._handler = NoteEventHandler(
            self.vector_store, self.config, self.debounce_seconds, callback
        )

        self._observer = Observer()
        self._observer.schedule(self._handler, str(notes_dir), recursive=True)
        self._observer.start()

        self._running = True
        console.print(f"[green]Started indexer watching: {notes_dir}[/green]")

    def stop(self):
        """Stop the file system observer."""
        if not self._running:
            return

        if self._observer:
            self._observer.stop()
            self._observer.join()

        self._running = False
        console.print("[green]Indexer stopped[/green]")

    def is_running(self) -> bool:
        """Check if the indexer is running."""
        return self._running

    def get_stats(self) -> IndexStats:
        """Get indexer statistics."""
        if self._handler:
            return self._handler.stats
        return IndexStats()

    def index_all(self, progress_callback: Optional[Callable[[int, int], None]] = None) -> int:
        """
        Perform full re-indexing of all notes.

        Args:
            progress_callback: Called with (current, total) for progress updates

        Returns:
            Number of notes indexed
        """
        from .note import NoteManager

        notes_dir = Path(self.config.notes_dir)
        if not notes_dir.exists():
            return 0

        # 清除旧索引数据，确保干净重建
        self.vector_store.clear()

        # Find all note files
        note_files = list(notes_dir.rglob("*.md"))
        total = len(note_files)

        if total == 0:
            return 0

        indexed = 0

        with Progress(
            SpinnerColumn(), TextColumn("[progress.description]{task.description}"), console=console
        ) as progress:
            task = progress.add_task(f"Indexing {total} notes...", total=total)

            for i, note_file in enumerate(note_files):
                try:
                    note = NoteManager.load_note(note_file)
                    if note:
                        self.vector_store.add_or_update_note(note)
                        indexed += 1

                        if self._handler:
                            self._handler.stats.total_indexed += 1

                    progress.update(task, advance=1)

                    if progress_callback:
                        progress_callback(i + 1, total)

                except Exception as e:
                    console.print(f"[red]Failed to index {note_file}: {e}[/red]")

        return indexed

    def index_note(self, note_id: str) -> bool:
        """
        Index a specific note by ID.

        Args:
            note_id: The note ID to index

        Returns:
            True if successful
        """
        from .note import NoteManager

        note_file = NoteManager.find_note_file(self.config, note_id)
        if not note_file:
            return False

        try:
            note = NoteManager.load_note(note_file)
            if note:
                self.vector_store.add_or_update_note(note)
                return True
        except Exception as e:
            console.print(f"[red]Failed to index {note_id}: {e}[/red]")

        return False

    def verify_index(self) -> Dict[str, any]:
        """
        Verify the index integrity.

        Returns:
            Dict with verification results
        """

        notes_dir = Path(self.config.notes_dir)
        if not notes_dir.exists():
            return {"error": "Notes directory not found"}

        # Get all note files
        note_files = list(notes_dir.rglob("*.md"))
        file_ids = {f.stem for f in note_files}

        # Get all indexed notes
        indexed_ids = set(self.vector_store.get_all_ids())

        missing_from_index = file_ids - indexed_ids
        orphaned_in_index = indexed_ids - file_ids

        return {
            "total_files": len(file_ids),
            "total_indexed": len(indexed_ids),
            "missing_from_index": list(missing_from_index),
            "orphaned_in_index": list(orphaned_in_index),
            "healthy": len(missing_from_index) == 0 and len(orphaned_in_index) == 0,
        }


class IndexerDaemon:
    """
    Daemon wrapper for running indexer in background.

    Usage:
        daemon = IndexerDaemon(config, vector_store)
        daemon.run()  # Blocks until stopped
    """

    def __init__(self, config: ZKConfig, vector_store: VectorStore):
        self.indexer = Indexer(config, vector_store)
        self._stop_event = threading.Event()

    def run(self):
        """Run the daemon until stopped."""
        self.indexer.start(callback=self._on_event)

        try:
            while not self._stop_event.is_set():
                self._stop_event.wait(1)
        except KeyboardInterrupt:
            pass
        finally:
            self.indexer.stop()

    def stop(self):
        """Signal the daemon to stop."""
        self._stop_event.set()

    def _on_event(self, event_type: str, message: str):
        """Handle indexer events."""
        timestamp = datetime.now().strftime("%H:%M:%S")
        if event_type == "error":
            console.print(f"[{timestamp}] [red]Error: {message}[/red]")
        else:
            console.print(f"[{timestamp}] [green]{event_type}: {message}[/green]")
