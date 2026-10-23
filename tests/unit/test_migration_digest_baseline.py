"""Frozen digest values recorded before the module migration (P01).

Receipts, batch IDs, OCR identities and cache keys already on disk were
computed with these exact serializations. Moving the functions must never
change a value; a new serialization needs a new name and a new identity.
"""
import hashlib
import json
from pathlib import PurePosixPath

from src.ocr.infrastructure.postprocessing.keyword_contract import dictionary_snapshot, digest
from src.ocr.runtime.config import config_hash
from src.ocr.runtime.paths import PROJECT_ROOT

FIXTURE = {"tên": "Báo cáo thường niên", "z": [3, 1.5, None, True], "a": {"b": "Ủy ban", "a": 2}}

# keyword_contract.digest: snapshot, batch_id, ocr_identity, manifest OCR hash.
COMPACT = "5c347d8d6ef1489f73abf139dbbc47c76183ebbe474f72197e0c828134704758"
# run_document generation and ProcessPageUseCase cache key (16 hex).
ASCII = "9dd4a95bc0c096b973d693d7fc68a5d3de6a91f566737b238547e6af738159e5"
# model_fingerprint (16 hex) and resolve_document_layout derived IDs (24 hex).
UNICODE = "bd051aaf9f1bdd7f370f1db3f8b83b81cf948c7afa89520e66e70bb39b45254a"
# config_hash: Unicode with default=str, 16 hex.
CONFIG_HASH = "d4f8d7afae8b0a3b"
# Keyword dictionary v1 shipped in config/keywords.txt.
SNAPSHOT_V1 = "6c132dc7338e6cf8de20e79824d0ad5da4465de5cc2c8e587c26db242e25d463"


def test_keyword_digest_is_compact_unicode_json():
    assert digest(FIXTURE) == COMPACT


def test_inline_ascii_and_unicode_serializations_are_unchanged():
    assert hashlib.sha256(json.dumps(FIXTURE, sort_keys=True).encode()).hexdigest() == ASCII
    payload = json.dumps(FIXTURE, sort_keys=True, ensure_ascii=False).encode("utf-8")
    assert hashlib.sha256(payload).hexdigest() == UNICODE


def test_config_hash_uses_default_str():
    assert config_hash({**FIXTURE, "path": PurePosixPath("models/vietocr/vgg_seq2seq.pth")}) == CONFIG_HASH


def test_keyword_v1_snapshot_hash():
    snapshot = dictionary_snapshot(PROJECT_ROOT / "config/keywords.txt", "v1")
    assert snapshot["snapshot_sha256"] == SNAPSHOT_V1
