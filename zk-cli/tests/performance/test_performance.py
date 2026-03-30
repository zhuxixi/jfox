"""Unit tests for performance module - 无需外部依赖"""
import pytest
import time
import logging
from unittest.mock import Mock, patch, MagicMock
from pathlib import Path

from zk.performance import (
    timer,
    BatchProcessor,
    ModelCache,
    PerformanceMonitor,
    get_perf_monitor,
)


class TestTimer:
    """测试 timer 装饰器"""
    
    def test_timer_logs_execution_time(self, caplog):
        """测试 timer 装饰器记录执行时间"""
        caplog.set_level(logging.INFO)
        
        @timer
        def slow_function():
            time.sleep(0.01)
            return 42
        
        result = slow_function()
        
        assert result == 42
        assert "slow_function took" in caplog.text
        assert "0.0" in caplog.text  # 至少记录了时间
    
    def test_timer_preserves_function_metadata(self):
        """测试 timer 装饰器保留函数元数据"""
        @timer
        def my_function():
            """My docstring"""
            pass
        
        assert my_function.__name__ == "my_function"
        assert my_function.__doc__ == "My docstring"


class TestBatchProcessor:
    """测试 BatchProcessor 类"""
    
    @pytest.fixture
    def processor(self):
        return BatchProcessor(batch_size=3)
    
    def test_process_empty_list(self, processor):
        """测试处理空列表"""
        results = processor.process([], lambda x: x * 2, show_progress=False)
        assert results == []
    
    def test_process_with_processor(self, processor):
        """测试正常处理"""
        items = [1, 2, 3, 4, 5]
        results = processor.process(items, lambda x: x * 2, show_progress=False)
        assert results == [2, 4, 6, 8, 10]
    
    def test_process_handles_errors(self, processor, caplog):
        """测试处理错误项"""
        caplog.set_level(logging.WARNING)
        
        def faulty_processor(x):
            if x == 3:
                raise ValueError("Error!")
            return x * 2
        
        items = [1, 2, 3, 4, 5]
        results = processor.process(items, faulty_processor, show_progress=False)
        
        # 错误项应被跳过
        assert len(results) == 4
        assert 6 not in results  # 3*2=6 因为出错未被添加
        assert "Failed to process item 2" in caplog.text  # index 2 is item 3
    
    def test_process_with_progress(self, processor):
        """测试带进度条的处理"""
        items = [1, 2, 3]
        results = processor.process(items, lambda x: x * 2, show_progress=True)
        assert results == [2, 4, 6]
    
    def test_process_embeddings_empty(self, processor):
        """测试空文本列表"""
        mock_backend = Mock()
        results = processor.process_embeddings([], mock_backend, show_progress=False)
        assert results == []
    
    def test_process_embeddings_success(self, processor):
        """测试正常嵌入处理"""
        import numpy as np
        
        mock_backend = Mock()
        mock_backend.encode.return_value = np.array([[0.1] * 384, [0.2] * 384])
        
        texts = ["text1", "text2"]
        results = processor.process_embeddings(texts, mock_backend, show_progress=False)
        
        assert len(results) == 2
        assert len(results[0]) == 384
        mock_backend.encode.assert_called_once()
    
    def test_process_embeddings_with_batching(self, processor):
        """测试批处理分割"""
        import numpy as np
        
        mock_backend = Mock()
        # 每个批次返回对应的嵌入
        mock_backend.encode.side_effect = [
            np.array([[0.1] * 384, [0.2] * 384, [0.3] * 384]),  # batch 1
            np.array([[0.4] * 384, [0.5] * 384]),  # batch 2
        ]
        
        texts = ["t1", "t2", "t3", "t4", "t5"]
        results = processor.process_embeddings(texts, mock_backend, show_progress=False)
        
        assert len(results) == 5
        assert mock_backend.encode.call_count == 2
    
    def test_process_embeddings_handles_errors(self, processor):
        """测试嵌入错误处理"""
        import numpy as np
        
        mock_backend = Mock()
        mock_model = Mock()
        mock_model.get_sentence_embedding_dimension.return_value = 384
        mock_backend.model = mock_model
        mock_backend.encode.side_effect = ValueError("Encode error")
        
        texts = ["text1", "text2"]
        results = processor.process_embeddings(texts, mock_backend, show_progress=False)
        
        # 错误时应返回零向量
        assert len(results) == 2
        assert results[0] == [0.0] * 384
        assert results[1] == [0.0] * 384


class TestModelCache:
    """测试 ModelCache 类"""
    
    def setup_method(self):
        """每个测试前清理缓存"""
        ModelCache.clear()
    
    def teardown_method(self):
        """每个测试后清理缓存"""
        ModelCache.clear()
    
    @patch('sentence_transformers.SentenceTransformer')
    def test_get_model_loads_new_model(self, mock_st_class):
        """测试首次加载模型"""
        mock_model = Mock()
        mock_st_class.return_value = mock_model
        
        result = ModelCache.get_model("test-model")
        
        assert result == mock_model
        mock_st_class.assert_called_once_with("test-model")
    
    @patch('sentence_transformers.SentenceTransformer')
    def test_get_model_uses_cache(self, mock_st_class):
        """测试缓存命中"""
        mock_model = Mock()
        mock_st_class.return_value = mock_model
        
        # 第一次调用
        result1 = ModelCache.get_model("test-model")
        # 第二次调用（应使用缓存）
        result2 = ModelCache.get_model("test-model")
        
        assert result1 == result2 == mock_model
        # 只加载一次
        mock_st_class.assert_called_once()
    
    @patch('sentence_transformers.SentenceTransformer')
    def test_get_model_respects_ttl(self, mock_st_class):
        """测试 TTL 过期后重新加载"""
        mock_model1 = Mock()
        mock_model2 = Mock()
        mock_st_class.side_effect = [mock_model1, mock_model2]
        
        # 第一次加载
        result1 = ModelCache.get_model("test-model")
        
        # 修改最后使用时间使其过期
        ModelCache._last_used = time.time() - 400  # TTL 是 300 秒
        
        # 再次获取（应重新加载）
        result2 = ModelCache.get_model("test-model")
        
        assert result1 == mock_model1
        assert result2 == mock_model2
        assert mock_st_class.call_count == 2
    
    def test_clear_removes_cache(self):
        """测试清除缓存"""
        with patch('sentence_transformers.SentenceTransformer') as mock_st:
            mock_st.return_value = Mock()
            ModelCache.get_model("test-model")
            assert ModelCache._instance is not None
            
            ModelCache.clear()
            
            assert ModelCache._instance is None
            assert ModelCache._last_used is None


class TestPerformanceMonitor:
    """测试 PerformanceMonitor 类"""
    
    def test_record_single_operation(self):
        """测试记录单个操作"""
        monitor = PerformanceMonitor()
        monitor.record("search", 0.5)
        
        assert "search" in monitor.metrics
        assert monitor.metrics["search"] == [0.5]
    
    def test_record_multiple_operations(self):
        """测试记录多个操作"""
        monitor = PerformanceMonitor()
        monitor.record("search", 0.5)
        monitor.record("search", 0.3)
        monitor.record("search", 0.7)
        
        assert len(monitor.metrics["search"]) == 3
    
    def test_record_different_operations(self):
        """测试记录不同类型的操作"""
        monitor = PerformanceMonitor()
        monitor.record("search", 0.5)
        monitor.record("index", 1.0)
        monitor.record("embed", 0.2)
        
        assert len(monitor.metrics) == 3
        assert "search" in monitor.metrics
        assert "index" in monitor.metrics
        assert "embed" in monitor.metrics
    
    def test_report_empty(self):
        """测试空报告"""
        monitor = PerformanceMonitor()
        report = monitor.report()
        
        assert report == {}
    
    def test_report_with_data(self):
        """测试有数据的报告"""
        monitor = PerformanceMonitor()
        monitor.record("search", 0.5)
        monitor.record("search", 0.3)
        monitor.record("search", 0.7)
        
        report = monitor.report()
        
        assert "search" in report
        search_stats = report["search"]
        assert search_stats["count"] == 3
        assert search_stats["total"] == 1.5
        assert search_stats["avg"] == 0.5
        assert search_stats["min"] == 0.3
        assert search_stats["max"] == 0.7
    
    def test_print_report(self, capsys):
        """测试打印报告"""
        monitor = PerformanceMonitor()
        monitor.record("search", 0.5)
        monitor.record("index", 1.0)
        
        monitor.print_report()
        
        captured = capsys.readouterr()
        assert "Performance Report" in captured.out
        assert "search" in captured.out
        assert "index" in captured.out
        assert "Count" in captured.out
        assert "Avg" in captured.out
    
    def test_print_report_sorts_by_total(self, capsys):
        """测试报告按总时间排序"""
        monitor = PerformanceMonitor()
        # 添加更多耗时数据，使 index 总时间 > search 总时间
        monitor.record("search", 0.5)
        monitor.record("index", 2.0)
        
        monitor.print_report()
        
        captured = capsys.readouterr()
        # index 应该排在 search 前面（因为它总时间更长）
        index_pos = captured.out.find("index")
        search_pos = captured.out.find("search")
        assert index_pos < search_pos


class TestGetPerfMonitor:
    """测试 get_perf_monitor 函数"""
    
    def test_returns_same_instance(self):
        """测试返回相同实例"""
        monitor1 = get_perf_monitor()
        monitor2 = get_perf_monitor()
        
        assert monitor1 is monitor2
    
    def test_is_performance_monitor(self):
        """测试返回 PerformanceMonitor 实例"""
        monitor = get_perf_monitor()
        
        assert isinstance(monitor, PerformanceMonitor)

pytestmark = [pytest.mark.performance, pytest.mark.slow]

