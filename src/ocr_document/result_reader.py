"""Read legacy results or the opt-in, versioned index into per-page JSON.

Compact export changes only result.json. Per-page files and V6 contracts
remain complete, so expanding the index restores the legacy consumer view.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict

from ocr_document.output_contract import RESULT_INDEX_SCHEMA


def load_document_json(path: str | Path) -> Dict[str, Any]:
    path = Path(path)
    if path.is_dir():
        path = path / "result.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("result.json must contain an object")
    schema = data.get("schema_version")
    if schema is None and "page_refs" not in data:
        return data
    if schema != RESULT_INDEX_SCHEMA:
        raise ValueError(f"Unsupported result.json schema: {schema!r}")
    if "pages" in data:
        raise ValueError("Compact result.json must use page_refs, without inline pages")
    selected = data.get("selected_pages")
    refs = data.get("page_refs")
    if (not isinstance(selected, list) or not selected
            or any(type(p) is not int or p < 1 for p in selected)
            or selected != sorted(set(selected))
            or not isinstance(refs, list) or len(refs) != len(selected)):
        raise ValueError("Compact result.json needs ordered, unique selected_pages and one reference per page")
    root = path.parent.resolve()
    pages = []
    for number, ref in zip(selected, refs):
        expected = f"pages/page-{number:04d}.json"
        if (not isinstance(ref, dict) or type(ref.get("page_num")) is not int
                or ref["page_num"] != number or ref.get("path") != expected):
            raise ValueError(f"Compact result.json: invalid reference for page {number}")
        page_path = (root / expected).resolve()
        if not page_path.is_relative_to(root):
            raise ValueError(f"Compact result.json: page {number} is outside the document directory")
        page = json.loads(page_path.read_text(encoding="utf-8"))
        if not isinstance(page, dict) or type(page.get("page_num")) is not int or page["page_num"] != number:
            raise ValueError(f"{expected}: page_num differs from its reference")
        pages.append(page)
    return {**{k: v for k, v in data.items() if k not in ("schema_version", "page_refs")}, "pages": pages}
