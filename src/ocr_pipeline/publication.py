"""Publish exactly one prepared revision before any subsequent document."""
from ocr_reporting.workbooks import matrix_bytes, verify_matrix
from ocr_artifacts.atomic_io import atomic_write_bytes
from ocr_artifacts.atomic_io import atomic_write_json
from ocr_pipeline.scheduler import sha256
from zipfile import BadZipFile
import json
from pathlib import Path


def publish_keyword_matrix(store, path, snapshot):
    revision, records, expected_hash = store.projection()
    identity = store.get("identity")
    for row in records:
        if row.get("outcome") == "SUCCEEDED":
            from ocr_pipeline.completion import verify_completed
            if not verify_completed(Path(row["output"])):
                raise ValueError("Accepted document is incomplete or changed before matrix publication")
            report_path=Path(row["output"])/"keyword_counts.json"
            if sha256(report_path) != row["report_sha256"]:
                raise ValueError("Accepted keyword report changed before matrix publication")
            report=json.loads(report_path.read_text(encoding="utf-8"))
            if report["display_counts"] != row["counts"] or report["identity"]["dictionary_sha256"] != snapshot["snapshot_sha256"]:
                raise ValueError("Prepared ledger counts differ from accepted report")
    queue = None
    if identity.get("config", {}).get("alias_rules") is not None:
        from ocr_pipeline.alias_finalization import publication_material
        records, queue = publication_material(records, snapshot, identity["config"], identity["batch_id"], revision)
    valid = False
    try:
        verify_matrix(path, identity["batch_id"], revision, records, snapshot)
        actual = sha256(path)
        valid = expected_hash is None or expected_hash == actual
    except (OSError, ValueError, KeyError, StopIteration, BadZipFile):
        pass
    if not valid:
        atomic_write_bytes(path, matrix_bytes(identity["batch_id"], revision, records, snapshot))
        verify_matrix(path, identity["batch_id"], revision, records, snapshot)
        actual = sha256(path)
    if queue is not None:
        queue_path = Path(path).parent / "new_suspicions_queue.json"
        atomic_write_json(queue_path, queue)
        if json.loads(queue_path.read_text(encoding="utf-8")) != queue:
            raise ValueError("Pending suspicion queue readback mismatch")
        store.put("new_suspicions_queue_sha256", sha256(queue_path))
    store.acknowledge(revision, actual)
    return revision
