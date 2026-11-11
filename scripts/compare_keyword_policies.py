"""Compare keyword counts under literal_v1 and the literal_v2 challenger (V8-032).

CPU only: it reads existing ``result.md`` files (or any UTF-8 text) and never runs
OCR or loads a model. literal_v1 stays the product policy; this report only shows
where literal_v2 would differ, split into the two changes it bundles:

- ``boundary``: v1 matches that are not on word boundaries;
- ``overlap``: bounded matches suppressed because a longer or earlier keyword won.

The difference is a diagnostic, not accuracy: deciding which policy is right needs
reviewed occurrences (``benchmark/scientific_evaluation/keyword_acceptance.py``).
Output is a new JSON file; an existing report is never overwritten.

Exit codes: 0 = report written, 2 = could not run.
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import sys
import unicodedata
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for entry in (ROOT / "src", ROOT):
    if str(entry) not in sys.path:
        sys.path.insert(0, str(entry))

from ocr_keywords.counter import KeywordCounter, _bounded_pattern, _normalize, resolve_literal_v2  # noqa: E402

SCHEMA = "ocr-keyword-policy-diff-v1"
EXAMPLES = 3


def _context(normalized: str, start: int, end: int) -> str:
    return normalized[max(0, start - 40):end + 40]


def compare_text(text: str, keywords: list[str]) -> dict:
    """Per-keyword v1/v2 counts with the cause of every difference."""
    keywords = KeywordCounter.unique_keywords(keywords)
    normalized = _normalize(text)
    v1 = {keyword: [] for keyword in keywords}
    for keyword, start, end in KeywordCounter.iter_occurrences(text, keywords):
        v1[keyword].append((start, end))
    kept, suppressed = resolve_literal_v2(text, keywords)
    v2 = {keyword: 0 for keyword in keywords}
    for keyword, _, _ in kept:
        v2[keyword] += 1
    rows = []
    for keyword in keywords:
        pattern = _bounded_pattern(keyword)
        # ``match(text, pos)`` still sees the characters around the span, so both
        # boundary assertions are checked against the whole text.
        unbounded = [(s, e) for s, e in v1[keyword]
                     if (m := pattern.match(normalized, s)) is None or m.end() != e]
        overlaps = [row for row in suppressed if row["keyword"] == keyword]
        if not unbounded and not overlaps and len(v1[keyword]) == v2[keyword]:
            continue
        rows.append({"keyword": keyword, "literal_v1": len(v1[keyword]), "literal_v2": v2[keyword],
                     "difference": v2[keyword] - len(v1[keyword]),
                     "boundary_rejected": len(unbounded),
                     "overlap_suppressed": len(overlaps),
                     "boundary_examples": [_context(normalized, s, e) for s, e in unbounded[:EXAMPLES]],
                     "overlap_examples": [{**row, "context": _context(normalized, row["match_start"], row["match_end"])}
                                          for row in overlaps[:EXAMPLES]]})
    return {"keywords": len(keywords),
            "literal_v1_total": sum(len(spans) for spans in v1.values()),
            "literal_v2_total": len(kept), "keywords_changed": len(rows), "changes": rows}


def _documents(paths: list[Path]) -> list[Path]:
    found = []
    for path in paths:
        if path.is_dir():
            found.extend(sorted(path.rglob("result.md")))
        elif path.is_file():
            found.append(path)
        else:
            raise FileNotFoundError(path)
    if not found:
        raise FileNotFoundError("No result.md or text file found in the given paths")
    return found


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Compare literal_v1 and literal_v2 keyword counts on CPU",
                                     allow_abbrev=False)
    parser.add_argument("inputs", nargs="+", type=Path, help="result.md files, text files or output directories")
    parser.add_argument("--keywords-file", type=Path, default=ROOT / "config/keywords.txt")
    parser.add_argument("--report", type=Path, required=True, help="New JSON report path (never overwritten)")
    args = parser.parse_args(argv)
    try:
        if args.report.exists():
            raise FileExistsError(f"Report exists: {args.report}")
        keywords = KeywordCounter.load_keywords(args.keywords_file)
        documents = []
        for path in _documents(args.inputs):
            raw = path.read_bytes()
            text = unicodedata.normalize("NFC", raw.decode("utf-8-sig"))
            documents.append({"path": str(path), "sha256": hashlib.sha256(raw).hexdigest(),
                              **compare_text(text, keywords)})
        report = {"schema_version": SCHEMA, "created_at": dt.datetime.now(dt.timezone.utc).isoformat(),
                  "keywords_file": str(args.keywords_file),
                  "keywords_sha256": hashlib.sha256(args.keywords_file.read_bytes()).hexdigest(),
                  "product_policy": "literal_v1", "challenger_policy": "literal_v2",
                  "quality_acceptance": "NOT_EVALUATED",
                  "totals": {"documents": len(documents),
                             "literal_v1": sum(d["literal_v1_total"] for d in documents),
                             "literal_v2": sum(d["literal_v2_total"] for d in documents)},
                  "documents": documents}
        args.report.parent.mkdir(parents=True, exist_ok=True)
        with args.report.open("x", encoding="utf-8") as stream:
            json.dump(report, stream, ensure_ascii=False, indent=2)
    except (OSError, ValueError) as exc:
        print(f"compare_keyword_policies: {exc}", file=sys.stderr)
        return 2
    totals = report["totals"]
    print(f"{totals['documents']} documents: literal_v1={totals['literal_v1']} literal_v2={totals['literal_v2']}; "
          f"quality NOT_EVALUATED -> {args.report}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
