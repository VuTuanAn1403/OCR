"""A disposable processing view of a PDF; the source file is never rewritten."""
from contextlib import contextmanager
import hashlib
from pathlib import Path

import pymupdf


@contextmanager
def processing_pdf(path, policy="original_v1", *, expected_sha256=None):
    """Normalize PDF objects in memory when the selected policy requires it.

    Some malformed object graphs crash MuPDF's native renderer, which cannot
    be caught with a Python exception. Normalization happens before rendering.
    Both phases use the same explicit, fingerprinted policy. The manifest
    retains the original source identity and separately records the view hash.
    This is a rendering workaround, not a claim of OCR accuracy or equivalence
    between independently supplied input versions.
    """
    if policy not in ("original_v1", "normalized_memory_v1"):
        raise ValueError(f"Unknown PDF render policy: {policy}")
    data = Path(path).read_bytes()
    source_hash = hashlib.sha256(data).hexdigest()
    if expected_sha256 is not None and source_hash != expected_sha256:
        raise ValueError("PDF source changed before opening the processing view")
    with pymupdf.open(stream=data, filetype="pdf") as source:
        if source.needs_pass:
            raise ValueError("Encrypted PDF requires authentication")
        provenance = {"policy": policy, "source_pdf_sha256": source_hash,
                      "view_pdf_sha256": source_hash, "source_file_modified": False}
        if policy == "original_v1":
            yield source, provenance
            return
        # Keep the trailer ID stable so phases A/B obtain identical view bytes.
        normalized = source.tobytes(garbage=3, deflate=True, no_new_id=True)
        provenance["view_pdf_sha256"] = hashlib.sha256(normalized).hexdigest()
        with pymupdf.open(stream=normalized, filetype="pdf") as view:
            if len(view) != len(source) or any(
                    view[n].rect != source[n].rect or view[n].rotation != source[n].rotation
                    for n in range(len(source))):
                raise ValueError("Normalized processing view changed page count or geometry")
            yield view, provenance
