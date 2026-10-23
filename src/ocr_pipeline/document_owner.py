"""One-document owner; finalizes keyword artifacts after all GPU children exit."""
import argparse
import json
from pathlib import Path
import sys
import psutil
from pydantic import ValidationError

from ocr_artifacts.atomic_io import atomic_write_json
from ocr_contracts.processing import PublicationError, IdentityMismatch
from ocr_contracts.protocol import DOCUMENT_WORKER_PROTOCOL, DocumentWorkerRequest


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--request",type=Path,required=True)
    parser.add_argument("--response",type=Path,required=True)
    args = parser.parse_args()
    payload = json.loads(args.request.read_text(encoding="utf-8"))
    # Echoed so the supervisor never accepts a response from another request
    # or attempt.
    echo = {"protocol": DOCUMENT_WORKER_PROTOCOL, "request_id": str(payload.get("request_id", "")),
            "attempt_id": str(payload.get("attempt_id", ""))}
    try:
        DocumentWorkerRequest.model_validate(payload)
        from ocr_pipeline.backend import verify_runtime
        verify_runtime(payload["request"])
        from ocr_pipeline.document import process_document
        result = process_document(payload["request"],payload["snapshot"],resume=payload["resume"])
        from ocr_runtime.fingerprint import assert_loaded_code_fingerprinted
        assert_loaded_code_fingerprinted()
        atomic_write_json(args.response,{**echo,"result":result})
    except Exception as exc:
        kind = "infrastructure" if isinstance(exc,ValidationError) else "identity" if isinstance(exc,IdentityMismatch) else "document" if isinstance(exc,TimeoutError) else "infrastructure" if (isinstance(exc,(OSError,PublicationError,psutil.AccessDenied)) or any(code in str(exc) for code in ("GPU_PHASE_PROCESS_TREE_SURVIVED", "UNFINGERPRINTED_CODE"))) else "document"
        error = f"{type(exc).__name__}: {exc}"
        atomic_write_json(args.response,{**echo,"kind":kind,"error":error,"transient":isinstance(exc,TimeoutError)})
        raise


if __name__ == "__main__":
    main()
