"""GPU vs CPU Performance Benchmark"""
import sys
sys.path.insert(0, 'zk-cli')

from zk.npu_backend import NPUAccelerator
import time
import numpy as np

print("=== GPU vs CPU Performance Benchmark ===")
print()

# Test texts of varying lengths
test_texts_short = [
    "This is a short note.",
    "Machine learning is interesting.",
    "Python is a great language.",
] * 10  # 30 short texts

test_texts_medium = [
    "This is a medium length note about machine learning and neural networks.",
    "Zettelkasten is a knowledge management system that helps organize thoughts.",
    "OpenVINO is a toolkit for optimizing and deploying deep learning models.",
] * 10  # 30 medium texts

test_texts_long = [
    "This is a longer text that simulates a typical note in a knowledge management system. "
    "It contains multiple sentences and ideas about various topics like machine learning, "
    "artificial intelligence, and natural language processing. "
    "The goal is to test how well the embedding model handles longer contexts.",
] * 10  # 10 long texts

all_tests = [
    ("Short (30 texts)", test_texts_short),
    ("Medium (30 texts)", test_texts_medium),
    ("Long (10 texts)", test_texts_long),
]

def benchmark_device(device_name, texts):
    """Benchmark a specific device"""
    # Create fresh accelerator for each device
    npu = NPUAccelerator(device=device_name)
    
    # Warm up
    print(f"  Warming up {device_name}...")
    _ = npu.encode(["warm up text"])
    
    # Benchmark
    print(f"  Running benchmark on {device_name}...")
    start = time.time()
    embeddings = npu.encode(texts, batch_size=8)
    elapsed = time.time() - start
    
    return elapsed, len(embeddings)

print("Loading models...")
print("(This will load on CPU first, then GPU)")
print()

results = []

for test_name, texts in all_tests:
    print(f"\n--- {test_name} ---")
    
    # CPU Benchmark
    try:
        cpu_time, cpu_count = benchmark_device("CPU", texts)
        print(f"  CPU: {cpu_time:.3f}s ({cpu_count} texts, {cpu_time/cpu_count*1000:.1f}ms/text)")
    except Exception as e:
        print(f"  CPU Error: {e}")
        cpu_time = None
    
    # GPU Benchmark
    try:
        gpu_time, gpu_count = benchmark_device("GPU", texts)
        print(f"  GPU: {gpu_time:.3f}s ({gpu_count} texts, {gpu_time/gpu_count*1000:.1f}ms/text)")
    except Exception as e:
        print(f"  GPU Error: {e}")
        gpu_time = None
    
    # Calculate speedup
    if cpu_time and gpu_time:
        speedup = cpu_time / gpu_time
        print(f"  Speedup: {speedup:.2f}x")
        results.append((test_name, speedup))

print("\n" + "="*50)
print("Summary:")
print("="*50)
for test_name, speedup in results:
    status = "GPU faster" if speedup > 1 else "CPU faster"
    print(f"{test_name}: {speedup:.2f}x ({status})")
