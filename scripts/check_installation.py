#!/usr/bin/env python3
"""
Automated Environment & Installation Verification Script.
Checks Python version, essential dependencies, and OCR engine availability.
"""

import sys
import importlib
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

REQUIRED_PACKAGES = [
    ("pymupdf", "PyMuPDF (fitz)"),
    ("cv2", "OpenCV (cv2)"),
    ("numpy", "NumPy"),
    ("PIL", "Pillow (PIL)"),
    ("rapidocr_onnxruntime", "RapidOCR"),
    ("onnxruntime", "ONNX Runtime"),
    ("vietocr", "VietOCR"),
    ("torch", "PyTorch"),
    ("torchvision", "TorchVision"),
    ("yaml", "PyYAML"),
    ("pytest", "Pytest"),
    ("tabulate", "Tabulate"),
    ("bs4", "BeautifulSoup4"),
    ("scipy", "SciPy"),
    ("apted", "APTED (TEDS Metric)"),
]

def check_python_version() -> bool:
    v = sys.version_info
    print(f"[*] Python Version: {v.major}.{v.minor}.{v.micro}")
    if v.major != 3 or v.minor < 10:
        print(f"    [FAIL] Python 3.10+ required. Current: {v.major}.{v.minor}", file=sys.stderr)
        return False
    if v.minor >= 13:
        print(f"    [WARNING] Python {v.major}.{v.minor} detected. PyTorch/VietOCR works best on Python 3.10-3.12.")
    else:
        print("    [OK] Supported Python version.")
    return True

def check_packages() -> bool:
    print("\n[*] Checking Required Packages:")
    all_ok = True
    for module_name, display_name in REQUIRED_PACKAGES:
        try:
            mod = importlib.import_module(module_name)
            ver = getattr(mod, "__version__", "installed")
            print(f"    [OK] {display_name:<24} (v{ver})")
        except ImportError as e:
            print(f"    [MISSING] {display_name:<24} - {e}", file=sys.stderr)
            all_ok = False
    return all_ok

def check_ocr_engines() -> bool:
    print("\n[*] Checking OCR Model Availability:")
    all_ok = True

    # 1. RapidOCR check
    try:
        from rapidocr_onnxruntime import RapidOCR
        import numpy as np
        engine = RapidOCR(intra_op_num_threads=2, inter_op_num_threads=1)
        dummy = np.full((64, 128, 3), 255, dtype=np.uint8)
        engine(dummy)
        print("    [OK] RapidOCR DBNet Engine: Ready")
    except Exception as e:
        print(f"    [FAIL] RapidOCR Engine Error: {e}", file=sys.stderr)
        all_ok = False

    # 2. VietOCR check
    try:
        import torch
        from src.ocr.infrastructure.ocr.vietnamese_seq2seq_engine import VietnameseSeq2SeqEngine
        from PIL import Image
        import numpy as np

        torch.set_num_threads(2)
        predictor = VietnameseSeq2SeqEngine(batch_size=4, device="cpu", num_threads=2)._recognizer
        dummy_crop = Image.fromarray(np.full((32, 100, 3), 255, dtype=np.uint8))
        _ = predictor.predict(dummy_crop)
        print("    [OK] VietOCR vgg_seq2seq Engine: Ready")
    except Exception as e:
        print(f"    [FAIL] VietOCR Engine Error: {e}", file=sys.stderr)
        all_ok = False

    # 3. DLA Engine check
    try:
        from src.ocr.infrastructure.layout.dla_engine import DLAEngine
        dla = DLAEngine()
        print("    [OK] V5.0 Document Layout Analysis (DLA) Engine: Ready")
    except Exception as e:
        print(f"    [FAIL] DLA Engine Error: {e}", file=sys.stderr)
        all_ok = False

    # 4. Scientific TEDS Metric check
    try:
        from benchmark.scientific_evaluation.teds_metric import compute_teds
        test_teds = compute_teds("<table><tr><td>1</td></tr></table>", "<table><tr><td>1</td></tr></table>")
        assert test_teds == 1.0
        print("    [OK] V5.0 Scientific Benchmark (TEDS/mAP/DER): Ready")
    except Exception as e:
        print(f"    [FAIL] TEDS Metric Error: {e}", file=sys.stderr)
        all_ok = False

    return all_ok

def main():
    print("=" * 60)
    print("VIETNAMESE OCR V5.0 - RESEARCH ENVIRONMENT VERIFICATION")
    print("=" * 60)

    py_ok = check_python_version()
    pkg_ok = check_packages()
    ocr_ok = check_ocr_engines()

    print("\n" + "=" * 60)
    if py_ok and pkg_ok and ocr_ok:
        print("Environment check: PASS")
        print("=" * 60)
        sys.exit(0)
    else:
        print("Environment check: FAIL", file=sys.stderr)
        print("Please resolve the issues above before running the pipeline.", file=sys.stderr)
        print("=" * 60)
        sys.exit(1)

if __name__ == "__main__":
    main()
