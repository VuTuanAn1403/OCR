"""Prepare locked GPU requests without loading Torch into the batch process."""
import copy
import json
import os
from pathlib import Path
import subprocess
import sys
import uuid

from ocr_runtime.config import ConfigError, declared_pipeline, load_profiles, get_profile
from ocr_runtime.pipeline_policy import PIPELINE, validate_profile
from ocr_contracts.protocol import DOCUMENT_WORKER_PROTOCOL
from ocr_pipeline.scheduler import ROOT, sha256
from ocr_runtime.fingerprint import code_fingerprints, source_fingerprint
from ocr_runtime.model_registry import model_selection, validate_registry
from ocr_runtime.paths import (absolute_path_env, models_dir, registry_model_path, source_tree,
                               vietocr_model_dir, worker_pythonpath)
from ocr_runtime.process_tree import PhaseExitError, ProcessTreeSurvived, supervised_run
from ocr_artifacts.atomic_io import atomic_write_json
from ocr_artifacts.digest import sha256_json_compact as digest
from ocr_contracts.processing import PublicationError, DocumentProcessingError, IdentityMismatch


def prepare_backend(config_path, profile, env_root, *, preflight=True):
    if not source_tree():
        # GPU workers load the project code through PYTHONPATH from a source
        # tree; an installed wheel would inject this interpreter's site-packages
        # into their separately locked runtimes (P10 decision).
        raise ValueError("NOT_SUPPORTED: V6.3 GPU backend runs from a checkout, not from an installed wheel")
    path, profiles = load_profiles(config_path)
    if declared_pipeline(path) != PIPELINE:
        raise ConfigError(f"{path} declares pipeline {declared_pipeline(path)!r}; V6.3 needs a v6.3 profile file")
    config = copy.deepcopy(get_profile(profiles, profile))
    validate_profile(config)
    registry_path = (ROOT/config["model_registry"]).resolve()
    registry = json.loads(registry_path.read_text(encoding="utf-8"))
    # Pin the files the phases will load, located like the engines locate
    # them (F06); a missing file fails here, before any model import.
    selection = validate_registry(registry)
    models = {selection[name]:checksum for name,checksum in registry["files"].items()}
    for name, checksum in models.items():
        if not Path(name).is_file():
            raise FileNotFoundError(f"MODEL_MISSING: {name} (registry {registry_path})")
        if sha256(name) != checksum:
            raise IdentityMismatch(f"MODEL_LOCK_MISMATCH: {name}")
    models[str(registry_path)] = sha256(registry_path)
    # Pin the bridge font along with other worker inputs. Resolve it without
    # importing PyMuPDF/Torch into this CPU-only supervisor.
    font = Path(os.environ.get("OCR_BRIDGE_FONT") or ROOT / "assets/fonts/NotoSans-Regular.ttf").absolute()
    if not font.is_file():
        raise FileNotFoundError(f"OCR bridge font missing: {font}")
    config["bridge_font"] = str(font)
    models[str(font)] = sha256(font)
    for name in ("text_detector","layout_model"):
        config[name] = dict(registry[name])
        config[name]["model_path"] = str(registry_model_path(config[name]["model_path"]).resolve())
    config["docling"]["device"] = "cuda"
    config["backend_devices"] = dict.fromkeys(("ocr_detection","ocr_recognition","layout","docling"),"cuda")
    suffix = "Scripts/python.exe" if os.name == "nt" else "bin/python"
    # Linux venv executables are symlinks. Resolving them launches the base
    # interpreter and drops the worker's site-packages.
    interpreters = {f"{role}_python":str((Path(env_root)/role/suffix).absolute()) for role in ("text","docling")}
    for python in interpreters.values():
        if not Path(python).is_file():
            raise FileNotFoundError(f"Missing locked GPU environment: {python}")
    platform = "windows" if os.name == "nt" else "linux"
    locks = {str(ROOT/"requirements/v62"/f"{platform}-{role}-gpu.lock"):None for role in ("text","docling")}
    locks = {p:sha256(p) for p in locks}
    config["docling"]["dependency_lock"] = next(p for p in locks if p.endswith("docling-gpu.lock"))
    if preflight:
        from ocr_runtime import gpu_lease, preflight as probes
        with gpu_lease.lease_for_gpu(gpu_lease.gpu_snapshot("cuda")):
            for role in ("text","docling"):
                probe = probes.inspect_environment(interpreters[f"{role}_python"],"cuda",require_ort=role=="text")
                if probe["status"] == "FAILED":
                    raise RuntimeError(f"GPU preflight failed for {role}: {probe['errors']}")
        probe = subprocess.run([interpreters["text_python"], "-c",
            "import sys; from ocr_structure.ocr_bridge import load_bridge_font; load_bridge_font(sys.argv[1])",
            str(font)], cwd=ROOT, capture_output=True, text=True, encoding="utf-8", timeout=30,
            env={**os.environ, **absolute_path_env(), "PYTHONPATH": worker_pythonpath()})
        if probe.returncode:
            raise RuntimeError(f"OCR bridge preflight failed: {probe.stderr[-2400:]}")
    fingerprints = code_fingerprints()
    # The model selection belongs to the snapshot (F06): document owners and
    # workers start with these directories, not with the environment of the
    # moment, and verify_runtime refuses an environment that now selects
    # other files.
    model_env = {"OCR_MODELS_DIR": str(models_dir().resolve()), "VIETOCR_MODEL_DIR": str(vietocr_model_dir().resolve())}
    return {"config":config,"config_path":str(path),"device":"cuda", **interpreters,
            "model_hashes":models,"lock_hashes":locks,"model_env":model_env,"model_selection":selection,
            "model_registry_path":str(registry_path),
            # ocr_identity uses the extraction closure only (P11a); the batch
            # still pins all closures so one batch never mixes code versions.
            "source_fingerprint":fingerprints["extraction"],"code_fingerprints":fingerprints,
            "phase_timeout":config["runtime"]["phase_timeout_seconds"],"lease_timeout":config["runtime"]["lease_timeout_seconds"]}


def verify_runtime(backend):
    if "code_fingerprints" in backend:
        changed = [name for name, value in code_fingerprints().items() if backend["code_fingerprints"].get(name) != value]
        if changed:
            raise IdentityMismatch(f"Source changed after batch snapshot: {', '.join(changed)} code")
    elif source_fingerprint() != backend["source_fingerprint"]:
        # Batches created before P11a pinned the fingerprint of all code.
        raise IdentityMismatch("Source changed after batch snapshot")
    for path, checksum in {**backend["model_hashes"],**backend["lock_hashes"]}.items():
        if sha256(path) != checksum:
            raise IdentityMismatch(f"Runtime input changed: {path}")
    if "model_selection" in backend:
        current = model_selection({"files": backend["model_selection"]})
        moved = sorted(name for name, path in backend["model_selection"].items() if current[name] != path)
        if moved:
            raise IdentityMismatch(f"MODEL_SELECTION_CHANGED: the environment now selects {moved[0]} "
                                   f"from {current[moved[0]]}, not the pinned {backend['model_selection'][moved[0]]}")
    if backend.get("model_registry_path"):
        validate_registry(json.loads(Path(backend["model_registry_path"]).read_text(encoding="utf-8")))


# Exit codes other than 0 after which a written result may still be accepted.
# Each entry needs a documented cause, log evidence and a test; none is
# accepted by default (D3). The tree must still be verified as exited.
ACCEPTED_NONZERO_EXIT_CODES: dict[int, str] = {}

DOCUMENT_WORKER_MODULE = "ocr_pipeline.document_owner"

# `source_fingerprint` is the extraction closure since P11a.
OCR_IDENTITY_KEYS = ("pdf_sha256", "config", "model_hashes", "lock_hashes", "source_fingerprint", "assets",
                     "output_mode", "text_python", "docling_python")


def ocr_identity(request):
    return digest({key: request[key] for key in OCR_IDENTITY_KEYS})


def read_worker_response(path, request_id=None):
    """Parse and validate a document-worker response (protocol P09)."""
    from pydantic import ValidationError
    from ocr_contracts.protocol import DocumentWorkerResponse
    try:
        raw = json.loads(Path(path).read_text(encoding="utf-8"))
    except ValueError as exc:
        raise PublicationError(f"Document worker response is not valid JSON: {exc}") from exc
    if not isinstance(raw, dict):
        raise PublicationError("Document worker response is not a JSON object")
    try:
        response = DocumentWorkerResponse.model_validate(raw).model_dump()
    except ValidationError as exc:
        raise PublicationError(f"Document worker response does not match the protocol schema: {exc}") from exc
    if request_id is not None and response["request_id"] != request_id:
        raise PublicationError("Document worker response belongs to another request")
    return response


def verify_document_result(response, request, snapshot, attempt_id):
    """The single acceptance check for a document worker result.

    A result is accepted only for this attempt, for the request's own output
    directory and OCR identity, and only while its receipts match the files.
    """
    from ocr_pipeline.document import valid_ocr, validate_gpu_source
    from ocr_pipeline.completion import verify_completed
    from ocr_keywords.contract import validate_report
    if response.get("attempt_id") != attempt_id:
        raise PublicationError("Document worker response does not belong to this attempt")
    result = response.get("result")
    if (not isinstance(result, dict) or result.get("outcome") != "SUCCEEDED"
            or any(not isinstance(result.get(key), str)
                   for key in ("output", "report_sha256", "completion_sha256", "validation"))):
        raise PublicationError("Document worker result does not match the result schema")
    output = Path(result["output"])
    if output.resolve() != (Path(request["output"]) / Path(request["pdf"]).stem).resolve():
        raise IdentityMismatch("Worker output directory differs from the request")
    try:
        if not valid_ocr(output, request["ocr_identity"]):
            raise ValueError("OCR receipt does not carry this request's identity")
        report_path = output / "keyword_counts.json"
        if (sha256(report_path) != result["report_sha256"] or not verify_completed(output)
                or sha256(output / "COMPLETED.json") != result["completion_sha256"]):
            raise ValueError("receipt differs from the artifacts on disk")
        validate_gpu_source(output)
        from ocr_pipeline.artifact_validation import validate_document_artifacts
        validation = validate_document_artifacts(output)
        if validation["status"] == "FAIL" or result["validation"] != validation["status"]:
            raise ValueError("Document validation differs from the accepted result")
        validate_report(json.loads(report_path.read_text(encoding="utf-8")), snapshot,
                        output / "result.md", output.name, request["pdf_sha256"])
    except (ValueError, KeyError, TypeError) as exc:
        raise IdentityMismatch(f"Worker result failed verification: {exc}") from exc
    return result


class GPUProcessor:
    def __init__(self, backend, *, assets="png", output_mode="compact"):
        self.backend, self.assets, self.output_mode = backend, assets, output_mode

    def request_for(self, item, output):
        request = {**self.backend,"pdf":item["path"],"pdf_sha256":item["pdf_sha256"],"output":str(output),
                   "assets":self.assets,"output_mode":self.output_mode,"finalize_document":False}
        request["ocr_identity"] = ocr_identity(request)
        return request

    def verify_existing(self, item, snapshot, output):
        """Recheck the OCR identity before accepting a resume skip/publication."""
        return verify_document_result({"attempt_id": "resume", "result": item},
                                      self.request_for(item, output), snapshot, "resume")

    def __call__(self, item, snapshot, output, *, resume, force_ocr, max_attempts=2):
        request = self.request_for(item, output)
        log_dir = Path(output)/"logs"
        request_id = uuid.uuid4().hex
        for attempt in range(max_attempts):
            attempt_id = uuid.uuid4().hex
            attempt_dir = log_dir / "requests" / item["id"] / request_id / attempt_id
            attempt_dir.mkdir(parents=True, exist_ok=False)
            request_path = attempt_dir / "request.json"
            response_path = attempt_dir / "response.json"
            atomic_write_json(request_path,{"protocol":DOCUMENT_WORKER_PROTOCOL,"request_id":request_id,
                                            "attempt_id":attempt_id,"request":request,"snapshot":snapshot,
                                            "resume":resume and not force_ocr})
            try:
                supervised_run([sys.executable,"-m",DOCUMENT_WORKER_MODULE,"--request",str(request_path),
                    "--response",str(response_path)],cwd=ROOT,env={**os.environ,**absolute_path_env(),**self.backend.get("model_env",{}),"PYTHONIOENCODING":"utf-8","PYTHONPATH":worker_pythonpath()},
                    log_path=attempt_dir/"worker.log",timeout=request["phase_timeout"]*3)
            except ProcessTreeSurvived as exc:
                # Never accept a result while a process of this document may
                # still hold the GPU, whatever the response file says.
                raise PublicationError(f"Document worker tree did not exit: {exc}") from exc
            except PhaseExitError as exc:
                if not response_path.is_file():
                    raise PublicationError(f"Document worker/tree did not yield a verifiable receipt: {exc}") from exc
                response = read_worker_response(response_path, request_id)
                if response["result"] is not None:
                    if exc.returncode not in ACCEPTED_NONZERO_EXIT_CODES:
                        raise PublicationError(f"Document worker exited with unclassified code {exc.returncode} "
                                               f"after writing a result: {exc}") from exc
                    return {**verify_document_result(response, request, snapshot, attempt_id), "attempts": attempt+1}
                if response.get("attempt_id") != attempt_id:
                    raise PublicationError("Document worker failure response does not belong to this attempt") from exc
                kind = response.get("kind") or "document"
                if kind == "infrastructure":
                    raise PublicationError(response.get("error", str(exc)))
                if kind == "identity":
                    raise IdentityMismatch(response.get("error", str(exc)))
                if not response.get("transient") or attempt+1 >= max_attempts:
                    raise DocumentProcessingError(response.get("error", str(exc)))
                continue
            if not response_path.is_file():
                raise PublicationError("Document worker exited without a response")
            response = read_worker_response(response_path, request_id)
            return {**verify_document_result(response, request, snapshot, attempt_id), "attempts": attempt+1}
