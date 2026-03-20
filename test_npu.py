"""NPU 驱动测试脚本"""
import sys
sys.path.insert(0, 'zk-cli')

from zk.npu_backend import get_npu_accelerator
import time

print('=== NPU Embedding Test ===')
print()

# 获取 NPU 加速器
npu = get_npu_accelerator()

# 健康检查
health = npu.health_check()
print('Health Check:')
print(f'  OpenVINO Available: {health["openvino_available"]}')
print(f'  Available Devices: {health["available_devices"]}')
print(f'  Selected Device: {health["selected_device"]}')
print()

# 测试编码
print('Loading model (first time may take a while)...')
start = time.time()
npu.load()
load_time = time.time() - start
print(f'Model loaded in {load_time:.2f}s on {npu.current_device}')
print()

# 测试单条编码
test_text = 'This is a test note for Zettelkasten knowledge management system.'
print(f'Text: "{test_text}"')
print('Encoding...')

start = time.time()
embedding = npu.encode_single(test_text)
encode_time = time.time() - start

print(f'Embedding dimension: {len(embedding)}')
print(f'Encoding time: {encode_time:.3f}s')
print(f'First 5 values: {embedding[:5]}')
print()

# 测试批量编码
print('Testing batch encoding...')
batch_texts = [
    'First test note about machine learning',
    'Second note about neural networks',
    'Third note about natural language processing',
]

start = time.time()
batch_embeddings = npu.encode(batch_texts, batch_size=3)
batch_time = time.time() - start

print(f'Batch size: {len(batch_texts)}')
print(f'Batch encoding time: {batch_time:.3f}s')
print(f'Average per text: {batch_time/len(batch_texts):.3f}s')
print()
print('[SUCCESS] NPU Embedding test passed!')
