"""NPU 加速器封装（Lunar Lake 优化）"""

import logging
from typing import List, Optional
import numpy as np

logger = logging.getLogger(__name__)


class NPUAccelerator:
    """NPU 加速器封装（Lunar Lake 优化）"""
    
    def __init__(self, model_name: str = "sentence-transformers/all-MiniLM-L6-v2", device: str = "auto"):
        self.model_name = model_name
        self.device = device
        self.model = None
        self._device_name = None
        
    def _detect_device(self) -> str:
        """自动检测最佳设备"""
        if self.device != "auto":
            return self.device
            
        try:
            import openvino as ov
            core = ov.Core()
            devices = core.available_devices
            
            # 优先级：NPU > GPU > CPU
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
        """加载模型"""
        if self.model is not None:
            return
            
        self._device_name = self._detect_device()
        
        try:
            from sentence_transformers import SentenceTransformer
            
            if self._device_name in ["NPU", "GPU"]:
                # 使用 OpenVINO 后端
                try:
                    self.model = SentenceTransformer(
                        self.model_name,
                        backend="openvino",
                        device=self._device_name
                    )
                    logger.info(f"Model loaded on {self._device_name}")
                except Exception as e:
                    logger.warning(f"Failed to load with OpenVINO backend: {e}, falling back to CPU")
                    self.model = SentenceTransformer(self.model_name)
                    self._device_name = "CPU"
            else:
                # CPU 模式
                self.model = SentenceTransformer(self.model_name)
                logger.info("Model loaded on CPU")
                
        except Exception as e:
            logger.error(f"Failed to load model: {e}")
            raise
    
    def encode(self, texts: List[str], batch_size: int = 32) -> np.ndarray:
        """编码文本"""
        if self.model is None:
            self.load()
            
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
    
    def encode_single(self, text: str) -> np.ndarray:
        """编码单条文本"""
        return self.encode([text])[0]
    
    @property
    def dimension(self) -> int:
        """向量维度"""
        return 384
    
    @property
    def current_device(self) -> str:
        """当前使用的设备"""
        return self._device_name or "unknown"
    
    def health_check(self) -> dict:
        """健康检查"""
        try:
            import openvino as ov
            core = ov.Core()
            devices = core.available_devices
            
            return {
                "openvino_available": True,
                "available_devices": devices,
                "selected_device": self._device_name,
                "model_loaded": self.model is not None,
            }
        except ImportError:
            return {
                "openvino_available": False,
                "available_devices": [],
                "selected_device": "CPU",
                "model_loaded": self.model is not None,
            }


# 全局 NPU 加速器实例
_npu_accelerator: Optional[NPUAccelerator] = None


def get_npu_accelerator() -> NPUAccelerator:
    """获取全局 NPU 加速器实例"""
    global _npu_accelerator
    if _npu_accelerator is None:
        _npu_accelerator = NPUAccelerator()
    return _npu_accelerator
