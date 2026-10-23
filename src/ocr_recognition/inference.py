"""Page OCR inference with a soft per-page deadline, moved verbatim from
ProcessPageUseCase._predict_image_counted (P09b). The owner holds the
per-page counters (`_current_page_ocr_calls`, `_active_page_deadline`), the
reused executor (`_ocr_executor`), `ocr_engine` and `_record_ocr_failure`.
"""
import logging
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeoutError, wait as wait_for_futures
from typing import Any, Dict, List, Optional

import numpy as np

logger = logging.getLogger(__name__)


def predict_image_counted(
    owner, img_bgr: np.ndarray, timeout_seconds: Optional[float] = None
) -> List[Dict[str, Any]]:
    owner._current_page_ocr_calls = getattr(owner, "_current_page_ocr_calls", 0) + 1
    timeout = timeout_seconds or getattr(owner, "_active_page_deadline", None)
    if timeout is not None and timeout > 0:
        # Reuse the inference thread for the whole document. Native CPU
        # runtimes may allocate thread-local pools on each calling thread;
        # a fresh executor for every page/retry causes resource churn.
        if getattr(owner, "_ocr_executor", None) is None:
            owner._ocr_executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="ocr-inference")
        future = owner._ocr_executor.submit(owner.ocr_engine.predict_image, img_bgr)
        try:
            return future.result(timeout=timeout)
        except FutureTimeoutError:
            logger.error("OCR exceeded %.2fs; waiting for in-flight inference to finish", timeout)
            owner._record_ocr_failure(f"OCR timed out after {timeout:.2f}s")
            # This remains a soft timeout: threads cannot stop native
            # inference. Drain it before fallback touches the shared model,
            # matching the previous executor context's shutdown(wait=True).
            wait_for_futures([future])
            return []
        except Exception as e:
            logger.exception("OCR execution failed")
            # Reported as a page error so an OCR crash is never
            # mistaken for a page that simply has no text.
            owner._record_ocr_failure(f"OCR failed: {type(e).__name__}: {e}")
            return []
    return owner.ocr_engine.predict_image(img_bgr)
