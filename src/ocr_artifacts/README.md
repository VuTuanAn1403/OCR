# ocr_artifacts

Hashing and atomic writes shared by the pipeline, workers, keywords and reporting.

- Public API: `hashing.sha256_file`; `digest.sha256_json_compact`, `digest.sha256_json_ascii`, `digest.sha256_json_unicode`; `atomic_io.atomic_write_text/bytes/json`.
- Allowed dependencies: standard library, `ocr_contracts`.
- The digest functions are distinct serializations already recorded in receipts, batch IDs, OCR identities and cache keys. Never merge them or change one; a new serialization gets a new name. `tests/unit/test_migration_digest_baseline.py` freezes their values.
- Tests: `tests/unit/artifacts/`.
