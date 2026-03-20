"""NPU Accelerator Wrapper (Lunar Lake Optimized)"""

import logging
from typing import List, Optional
import numpy as np

logger = logging.getLogger(__name__)


class NPUAccelerator:
    """NPU Accelerator Wrapper (Lunar Lake Optimized)"""
    
    def __init__(self, model_name: str = "sentence-transformers/all-MiniLM-L6-v2", device: str = "auto"):
        self.model_name = model_name
        self.device = device
        self.model = None
        self._device_name = None
        self._use_optimum = False
        
    def _detect_device(self) -> str:
        """Auto-detect best device"""
        if self.device != "auto":
            return self.device
            
        try:
            import openvino as ov
            core = ov.Core()
            devices = core.available_devices
            
            # Priority: NPU > GPU > CPU
            if "NPU" in devices:
                logger.info("NPU device detected")
                return "NPU"
            elif "GPU" in devices:
                logger.info("GPU device detected")
                return "GPU"
            else:
                logger.info("Using CPU device")
                return "CPU"
        except ImportError:
            logger.warning("OpenVINO not installed, using CPU")
            return "CPU"
    
    def load(self):
        """Load model"""
        if self.model is not None:
            return
            
        self._device_name = self._detect_device()
        
        # Try to use Optimum for NPU first
        if self._device_name == "NPU":
            try:
                self._load_with_optimum_npu()
                self._use_optimum = True
                logger.info(f"Model loaded on {self._device_name} using Optimum")
                return
            except Exception as e:
                logger.warning(f"Failed to load with Optimum on NPU: {e}")
                # Try GPU as fallback
                try:
                    logger.info("Trying GPU...")
                    self._load_with_optimum_gpu()
                    self._device_name = "GPU"
                    self._use_optimum = True
                    logger.info(f"Model loaded on GPU using Optimum")
                    return
                except Exception as e2:
                    logger.warning(f"Failed to load on GPU: {e2}, falling back to CPU")
                    self._device_name = "CPU"
        
        # Fallback to sentence-transformers
        try:
            from sentence_transformers import SentenceTransformer
            
            self.model = SentenceTransformer(self.model_name)
            logger.info(f"Model loaded on {self._device_name}")
            
        except Exception as e:
            logger.error(f"Failed to load model: {e}")
            raise
    
    def _load_with_optimum_npu(self):
        """Load model using Optimum for NPU support with static shapes"""
        try:
            from optimum.intel import OVModelForFeatureExtraction
            from transformers import AutoTokenizer
            import openvino as ov
            
            # Check if we have a pre-compiled model for NPU
            cache_dir = ov.Core().get_property("NPU", "CACHE_DIR") if "NPU" in ov.Core().available_devices else None
            
            # Load model with static shapes for NPU
            # Use batch_size=1, seq_length=128 for compatibility
            self.model = OVModelForFeatureExtraction.from_pretrained(
                self.model_name,
                export=True,
                device="NPU",
                ov_config={
                    "CACHE_DIR": "",
                    "PERFORMANCE_HINT": "LATENCY",
                }
            )
            self.tokenizer = AutoTokenizer.from_pretrained(self.model_name)
            
        except ImportError:
            logger.error("Optimum or transformers not installed")
            raise
    
    def _load_with_optimum_gpu(self):
        """Load model using Optimum for GPU support"""
        try:
            from optimum.intel import OVModelForFeatureExtraction
            from transformers import AutoTokenizer
            
            self.model = OVModelForFeatureExtraction.from_pretrained(
                self.model_name,
                export=True,
                device="GPU"
            )
            self.tokenizer = AutoTokenizer.from_pretrained(self.model_name)
            
        except ImportError:
            logger.error("Optimum or transformers not installed")
            raise
    
    def encode(self, texts: List[str], batch_size: int = 32) -> np.ndarray:
        """Encode texts"""
        if self.model is None:
            self.load()
        
        if self._use_optimum:
            return self._encode_with_optimum(texts)
        else:
            return self._encode_with_st(texts, batch_size)
    
    def _encode_with_st(self, texts: List[str], batch_size: int = 32) -> np.ndarray:
        """Encode using sentence-transformers"""
        try:
            return self.model.encode(
                texts, 
                batch_size=batch_size, 
                show_progress_bar=False,
                convert_to_numpy=True
            )
        except Exception as e:
            logger.error(f"Encoding failed: {e}")
            raise
    
    def _encode_with_optimum(self, texts: List[str]) -> np.ndarray:
        """Encode using Optimum"""
        import torch
        
        embeddings = []
        for text in texts:
            inputs = self.tokenizer(text, return_tensors="pt", padding=True, truncation=True, max_length=128)
            with torch.no_grad():
                outputs = self.model(**inputs)
            # Use mean pooling
            attention_mask = inputs['attention_mask']
            token_embeddings = outputs.last_hidden_state
            input_mask_expanded = attention_mask.unsqueeze(-1).expand(token_embeddings.size()).float()
            sum_embeddings = torch.sum(token_embeddings * input_mask_expanded, 1)
            sum_mask = torch.clamp(input_mask_expanded.sum(1), min=1e-9)
            embedding = (sum_embeddings / sum_mask).squeeze().numpy()
            embeddings.append(embedding)
        
        return np.array(embeddings)
    
    def encode_single(self, text: str) -> np.ndarray:
        """Encode single text"""
        return self.encode([text])[0]
    
    @property
    def dimension(self) -> int:
        """Embedding dimension"""
        return 384
    
    @property
    def current_device(self) -> str:
        """Current device being used"""
        return self._device_name or "unknown"
    
    def health_check(self) -> dict:
        """Health check"""
        try:
            import openvino as ov
            core = ov.Core()
            devices = core.available_devices
            
            return {
                "openvino_available": True,
                "available_devices": devices,
                "selected_device": self._device_name,
                "model_loaded": self.model is not None,
                "using_optimum": self._use_optimum,
            }
        except ImportError:
            return {
                "openvino_available": False,
                "available_devices": [],
                "selected_device": "CPU",
                "model_loaded": self.model is not None,
                "using_optimum": False,
            }


# Global NPU accelerator instance
_npu_accelerator: Optional[NPUAccelerator] = None


def get_npu_accelerator() -> NPUAccelerator:
    """Get global NPU accelerator instance"""
    global _npu_accelerator
    if _npu_accelerator is None:
        _npu_accelerator = NPUAccelerator()
    return _npu_accelerator
