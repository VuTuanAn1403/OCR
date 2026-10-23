"""Named canonical JSON digests (full SHA-256 hex; callers truncate).

Each function is one serialization already used in persisted identities.
They differ on purpose and must never be merged or changed.
"""
from __future__ import annotations

import hashlib
import json
from typing import Any, Callable, Optional


def sha256_json_compact(value: Any) -> str:
    """Keyword snapshot, batch_id, ocr_identity, manifest OCR hash."""
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                     separators=(",", ":")).encode()).hexdigest()


def sha256_json_ascii(value: Any) -> str:
    """Two-phase scheduler generation, page cache key (16 hex)."""
    return hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()


def sha256_json_unicode(value: Any, *, default: Optional[Callable[[Any], Any]] = None) -> str:
    """config_hash (with default=str, 16 hex), model_fingerprint (16 hex),
    derived layout source IDs (24 hex)."""
    payload = json.dumps(value, sort_keys=True, ensure_ascii=False, default=default)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()
