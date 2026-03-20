"""Large Batch Benchmark"""
import sys
sys.path.insert(0, 'zk-cli')

from zk.npu_backend import NPUAccelerator
import time

print("=== Large Batch Benchmark ===")
print()

# Generate 100 test texts
texts = [f"This is test note number {i} about knowledge management and machine learning concepts." for i in range(100)]

print("Testing with 100 texts...")
print()

# CPU Test
print("CPU:")
npu_cpu = NPUAccelerator(device="CPU")
_ = npu_cpu.encode(["warmup"])  # Warmup

start = time.time()
embeddings_cpu = npu_cpu.encode(texts, batch_size=32)
cpu_time = time.time() - start
print(f"  Time: {cpu_time:.3f}s")
print(f"  Per text: {cpu_time/len(texts)*1000:.2f}ms")

# GPU Test
print("\nGPU:")
npu_gpu = NPUAccelerator(device="GPU")
_ = npu_gpu.encode(["warmup"])  # Warmup

start = time.time()
embeddings_gpu = npu_gpu.encode(texts, batch_size=32)
gpu_time = time.time() - start
print(f"  Time: {gpu_time:.3f}s")
print(f"  Per text: {gpu_time/len(texts)*1000:.2f}ms")

# Summary
print("\n" + "="*50)
if gpu_time < cpu_time:
    speedup = cpu_time / gpu_time
    print(f"GPU is {speedup:.2f}x faster than CPU")
else:
    slowdown = gpu_time / cpu_time
    print(f"CPU is {slowdown:.2f}x faster than GPU")

print(f"\nGPU overhead: ~{gpu_time - cpu_time:.3f}s")
print("="*50)
