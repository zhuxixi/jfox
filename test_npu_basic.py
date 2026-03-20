"""NPU Basic Test (No Network Required)"""
import openvino as ov
import numpy as np

print("=== NPU Driver Basic Test ===")
print()

# 1. OpenVINO Version
print(f"OpenVINO Version: {ov.__version__}")
print()

# 2. Get Core Instance
core = ov.Core()

# 3. List All Available Devices
devices = core.available_devices
print(f"Available Devices: {devices}")
print()

# 4. Check NPU
if "NPU" in devices:
    print("[OK] NPU device detected!")
    
    # Get NPU Info
    try:
        npu_full_name = core.get_property("NPU", "FULL_DEVICE_NAME")
        print(f"   Device Name: {npu_full_name}")
    except Exception as e:
        print(f"   Device Name Error: {e}")
    
    print()
    print("=" * 50)
    print("NPU Driver Status: READY")
    print("=" * 50)
    print()
    print("Note: Model download requires Hugging Face access.")
    print("For offline use, download models manually to:")
    print("  ~/.cache/torch/sentence_transformers/")
    
else:
    print("[ERROR] NPU device not detected")
    print()
    print("Please check:")
    print("  1. Intel AI Boost driver installation")
    print("  2. Device Manager NPU status")
    print("  3. OpenVINO NPU plugin")

print()
print("Test completed!")
