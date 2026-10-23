"""Exclusive GPU lease and VRAM snapshot, held across all phases of a document.

The kernel releases the lock when the holder dies; no stale-PID guessing.
Standard library only (nvidia-smi through subprocess); never imports Torch.
"""
from __future__ import annotations

import os
from pathlib import Path
import subprocess
import time

from ocr_runtime.paths import PROJECT_ROOT


class GPULease:
    """Kernel releases the lock after supervisor death; no stale-PID guessing."""
    def __init__(self, path, timeout=60):
        self.path, self.timeout, self.stream = Path(path), timeout, None

    def __enter__(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.stream = self.path.open("a+b")
        self.stream.seek(0, 2)
        if self.stream.tell() == 0:
            self.stream.write(b"0")
            self.stream.flush()
        deadline = time.monotonic() + self.timeout
        while True:
            try:
                self.stream.seek(0)
                if os.name == "nt":
                    import msvcrt
                    msvcrt.locking(self.stream.fileno(), msvcrt.LK_NBLCK, 1)
                else:
                    import fcntl
                    fcntl.flock(self.stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
                return self
            except OSError:
                if time.monotonic() >= deadline:
                    self.stream.close()
                    raise TimeoutError(f"GPU_LEASE_BUSY: {self.path}")
                time.sleep(.1)

    def __exit__(self, *_):
        self.stream.seek(0)
        if os.name == "nt":
            import msvcrt
            msvcrt.locking(self.stream.fileno(), msvcrt.LK_UNLCK, 1)
        else:
            import fcntl
            fcntl.flock(self.stream, fcntl.LOCK_UN)
        self.stream.close()


def gpu_snapshot(device):
    if device == "cpu":
        return {"device": "cpu"}
    cmd = ["nvidia-smi", "--query-gpu=uuid,memory.total,memory.used", "--format=csv,noheader,nounits", "--id=0"]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=10,
                            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
    if result.returncode:
        raise RuntimeError("nvidia-smi VRAM audit unavailable: " + result.stderr[-500:])
    uuid, total, used = result.stdout.strip().splitlines()[0].split(",")
    return {"device": uuid.strip(), "total_mib": int(total), "used_mib": int(used)}


def lease_for_gpu(snapshot, timeout=60):
    directory = Path(os.getenv("OCR_GPU_LEASE_DIR", str(PROJECT_ROOT / ".cache/gpu-leases")))
    name = snapshot["device"].replace("/", "_").replace(":", "_") + ".lock"
    return GPULease(directory / name, timeout=timeout)
