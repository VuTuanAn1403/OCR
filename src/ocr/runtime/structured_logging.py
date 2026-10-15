"""Structured logging (proposal V6 ENV-11).

`--log-format json` writes one JSON object per line to stderr, each carrying
`run_id`, `doc_id`, `page`, `stage` and `worker`. The default text mode keeps
the console exactly as before: page progress is printed and logging is not
reconfigured. Pool workers inherit the mode through OCR_LOG_FORMAT.
"""
from __future__ import annotations

import contextvars
import json
import logging
import multiprocessing
import os
import sys
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Any, Dict, Optional

LOG_FORMATS = ("text", "json")
CONTEXT_FIELDS = ("run_id", "doc_id", "page", "stage", "worker")
_ENV = "OCR_LOG_FORMAT"
_CONTEXT: contextvars.ContextVar[Dict[str, Any]] = contextvars.ContextVar("ocr_log_context", default={})
_PROGRESS = logging.getLogger("ocr.progress")


@contextmanager
def log_context(**fields):
    """Bind context fields for logs emitted inside the block."""
    token = bind_context(**fields)
    try:
        yield
    finally:
        reset_context(token)


def bind_context(**fields) -> contextvars.Token:
    """Bind fields until `reset_context(token)`; for spans too long for a `with`."""
    return _CONTEXT.set({**_CONTEXT.get(), **{k: v for k, v in fields.items() if v is not None}})


def reset_context(token: contextvars.Token) -> None:
    _CONTEXT.reset(token)


def current_context() -> Dict[str, Any]:
    return dict(_CONTEXT.get())


def _worker_name() -> str:
    process = multiprocessing.current_process()
    return "main" if process.name == "MainProcess" else f"{process.name}:{os.getpid()}"


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        context = _CONTEXT.get()
        payload = {"ts": datetime.fromtimestamp(record.created, timezone.utc).isoformat(),
                   "level": record.levelname, "logger": record.name, "message": record.getMessage()}
        for key in CONTEXT_FIELDS:
            # Explicit `extra=` wins over the bound context.
            payload[key] = getattr(record, key, None) if getattr(record, key, None) is not None \
                else context.get(key)
        payload["worker"] = payload["worker"] or _worker_name()
        if getattr(record, "ocr_fields", None):
            payload["data"] = record.ocr_fields
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=False, default=str)


def json_logging_enabled() -> bool:
    return os.getenv(_ENV) == "json"


def configure_logging(log_format: str = "text", level: int = logging.INFO, stream=None) -> None:
    """Install the JSON handler for `json`; `text` leaves logging untouched."""
    if log_format not in LOG_FORMATS:
        raise ValueError(f"log format must be one of {', '.join(LOG_FORMATS)}")
    os.environ[_ENV] = log_format
    root = logging.getLogger()
    for handler in [h for h in root.handlers if getattr(h, "_ocr_structured", False)]:
        root.removeHandler(handler)
        root.setLevel(handler._ocr_previous_level)
    if log_format == "text":
        return
    handler = logging.StreamHandler(stream or sys.stderr)
    handler.setFormatter(JsonFormatter())
    handler._ocr_structured = True
    handler._ocr_previous_level = root.level
    root.addHandler(handler)
    root.setLevel(level)


def progress(message: str, *, stage: Optional[str] = None, level: int = logging.INFO, file=None,
             **fields: Any) -> None:
    """Progress/status line: printed in text mode (unchanged console, `file`
    as for print), a log event in JSON mode. Context fields passed here
    (e.g. doc_id) override the bound context; the rest go under `data`."""
    if json_logging_enabled():
        context = {key: fields.pop(key) for key in CONTEXT_FIELDS if key in fields}
        _PROGRESS.log(level, message.strip(), extra={"stage": stage, **context, "ocr_fields": fields})
    else:
        print(message, file=file)
