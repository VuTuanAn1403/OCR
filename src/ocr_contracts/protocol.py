"""Versioned process protocols (P09). Requests and responses are JSON files
with artifact paths, never pickled objects, model instances or shell
commands. A response from another protocol version or another attempt is
rejected by the supervisor."""
from __future__ import annotations

from typing import Any, Dict, Literal, Optional

from pydantic import BaseModel, ConfigDict

DOCUMENT_WORKER_PROTOCOL = "document-worker-v1"
# Recorded in every phase identity; checkpoints of another protocol never match.
PHASE_PROTOCOL = "document-two-phase-v1"


class DocumentWorkerRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    protocol: Literal["document-worker-v1"]
    request_id: str
    attempt_id: str
    request: Dict[str, Any]
    snapshot: Dict[str, Any]
    resume: bool


class DocumentResult(BaseModel):
    outcome: Literal["SUCCEEDED"]
    output: str
    report_sha256: str
    completion_sha256: str
    validation: str


class DocumentWorkerResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    protocol: Literal["document-worker-v1"]
    request_id: str
    attempt_id: str
    result: Optional[DocumentResult] = None
    kind: Optional[Literal["document", "identity", "infrastructure"]] = None
    error: Optional[str] = None
    transient: bool = False
