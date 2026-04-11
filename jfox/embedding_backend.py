"""Embedding Backend - CPU Only (Simplified)"""

import logging
from typing import List, Optional

import numpy as np

logger = logging.getLogger(__name__)


class EmbeddingBackend:
    """Simple CPU-based embedding backend"""

    def __init__(self, model_name: str = "sentence-transformers/all-MiniLM-L6-v2"):
        self.model_name = model_name
        self.model = None

    def load(self):
        """Load the model"""
        if self.model is not None:
            return

        try:
            from sentence_transformers import SentenceTransformer

            self.model = SentenceTransformer(self.model_name)
            logger.info(f"Model loaded: {self.model_name}")
        except Exception as e:
            logger.error(f"Failed to load model: {e}")
            raise

    def encode(self, texts: List[str], batch_size: int = 32) -> np.ndarray:
        """Encode texts to embeddings"""
        if self.model is None:
            self.load()

        try:
            return self.model.encode(
                texts, batch_size=batch_size, show_progress_bar=False, convert_to_numpy=True
            )
        except Exception as e:
            logger.error(f"Encoding failed: {e}")
            raise

    def encode_single(self, text: str) -> np.ndarray:
        """Encode a single text"""
        return self.encode([text])[0]

    @property
    def dimension(self) -> int:
        """Return embedding dimension"""
        return 384


# Global backend instance
_backend: Optional[EmbeddingBackend] = None


def get_backend() -> EmbeddingBackend:
    """Get global embedding backend instance"""
    global _backend
    if _backend is None:
        _backend = EmbeddingBackend()
    return _backend
