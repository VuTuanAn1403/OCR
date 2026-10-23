"""Device selection (ENV-01, T4). The default stays `cpu` so measurements
against the agreed CPU requirements (REQ-01..03) are not silently moved to GPU."""
from __future__ import annotations

VALID_DEVICES = ("auto", "cpu", "cuda")


def cuda_available() -> bool:
    try:
        import torch
    except ImportError:
        return False
    return bool(torch.cuda.is_available())


def resolve_device(requested: str | None) -> str:
    """Map `auto|cpu|cuda` to a concrete `cpu` or `cuda`."""
    device = (requested or "cpu").lower()
    if device not in VALID_DEVICES:
        raise ValueError(f"Unsupported device '{requested}'. Use one of: {', '.join(VALID_DEVICES)}")
    if device == "cpu":
        return "cpu"
    available = cuda_available()
    if device == "cuda" and not available:
        raise RuntimeError("Device 'cuda' requested but torch reports no CUDA device")
    return "cuda" if available else "cpu"
