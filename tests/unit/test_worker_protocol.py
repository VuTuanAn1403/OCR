"""P09 process protocol: versioned JSON requests/responses, workers started by
module name, supervisor imports no GPU library."""
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest
from pydantic import ValidationError

from ocr_contracts.protocol import DOCUMENT_WORKER_PROTOCOL, DocumentWorkerRequest, DocumentWorkerResponse
from ocr_pipeline import backend, scheduler

ROOT = Path(__file__).resolve().parents[2]


def test_request_and_response_models_reject_unknown_versions_and_fields():
    request = {"protocol": DOCUMENT_WORKER_PROTOCOL, "request_id": "r", "attempt_id": "a", "request": {},
               "snapshot": {}, "resume": False}
    DocumentWorkerRequest.model_validate(request)
    for bad in ({**request, "protocol": "document-worker-v0"}, {**request, "command": "rm -rf /"}):
        with pytest.raises(ValidationError):
            DocumentWorkerRequest.model_validate(bad)
    with pytest.raises(ValidationError):
        DocumentWorkerResponse.model_validate({"protocol": DOCUMENT_WORKER_PROTOCOL, "request_id": "r",
                                               "attempt_id": "a", "kind": "unknown"})


def test_document_owner_rejects_malformed_request(tmp_path):
    request, response = tmp_path / "request.json", tmp_path / "response.json"
    request.write_text(json.dumps({"protocol": "document-worker-v0", "request_id": "r", "attempt_id": "a"}),
                       encoding="utf-8")
    env = {**os.environ, "PYTHONPATH": os.pathsep.join([str(ROOT), str(ROOT / "src")])}
    result = subprocess.run([sys.executable, "-m", backend.DOCUMENT_WORKER_MODULE, "--request", str(request),
                             "--response", str(response)], cwd=ROOT, env=env, capture_output=True, text=True,
                            timeout=120)
    assert result.returncode != 0
    answer = DocumentWorkerResponse.model_validate(json.loads(response.read_text(encoding="utf-8")))
    assert answer.kind == "infrastructure" and answer.result is None and answer.attempt_id == "a"


def test_workers_are_started_by_module_name():
    assert backend.DOCUMENT_WORKER_MODULE == "ocr_pipeline.document_owner"
    source = Path(scheduler.__file__).read_text(encoding="utf-8")
    assert '"-m", "ocr_workers.phases"' in source


def test_supervisor_and_document_owner_import_no_gpu_library():
    code = ("import json, sys\nimport ocr_pipeline.cli, ocr_pipeline.backend, ocr_pipeline.scheduler, "
            "ocr_pipeline.document_owner, ocr_pipeline.batch, ocr_pipeline.analysis_run\n"
            "print(json.dumps(sorted(m for m in ('torch','vietocr','onnxruntime','docling','transformers','cv2') "
            "if m in sys.modules)))")
    env = {**os.environ, "PYTHONPATH": os.pathsep.join([str(ROOT), str(ROOT / "src")])}
    result = subprocess.run([sys.executable, "-c", code], cwd=ROOT, env=env, capture_output=True, text=True,
                            timeout=120)
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout) == []
