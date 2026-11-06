"""Hold a temporary Windows execution request during an active operation."""
from contextlib import contextmanager
import ctypes
import os


@contextmanager
def keep_system_awake():
    if os.name != "nt":
        yield {"method": "platform_default"}
        return
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    function = kernel.SetThreadExecutionState
    function.argtypes = [ctypes.c_uint32]
    function.restype = ctypes.c_uint32
    previous = function(0x80000001)  # ES_CONTINUOUS | ES_SYSTEM_REQUIRED.
    if not previous:
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        yield {"method": "SetThreadExecutionState", "system_required": True}
    finally:
        if not function(previous | 0x80000000):
            raise ctypes.WinError(ctypes.get_last_error())
