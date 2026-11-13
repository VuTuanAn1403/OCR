#!/usr/bin/env python3
"""Keyword occurrences of OCR outputs against the screened text layer, per page (V8-100).

CPU only, read-only. For every development PDF whose screening is ACCEPTED and every CANDIDATE page
of the locked inventory, the reference is the visible text-layer words
(``measure_text_layer_diacritics.reference_lines``, lock v8 reference text) and the prediction is the
production page text (``run_vlm_challenger.product_texts``). Both are whitespace-collapsed and
counted with the production counter (``KeywordCounter.iter_occurrences``, ``literal_v1``).

Per (page, keyword): ``missing`` = reference minus prediction when positive, ``extra`` = the
reverse. With two outputs, a (page, keyword) cell is ``fixed`` when the candidate's error
(missing + extra) is smaller than the baseline's, ``harmed`` when larger.

Review tier (``review_tier``): literal counting is only tier 1. The product also lists diacritic
alias candidates for review (``ocr_keywords.alias_map.find_alias_candidates``, multi-word phrases)
and the challenger ``benchmark.challengers.keyword_confusables`` lists alphanumeric keywords read
with a look-alike character (``020`` for ``O2O``). Per (page, keyword) the missing occurrences are
covered first by alias candidates, then by confusable candidates; a candidate left over has no
reference occurrence behind it and would be a false count if a reviewer accepted it. Candidates
are found on the page text; the product runs the alias finder on the whole ``result.md``.

The text layer is development evidence, not independent keyword GT: quality stays NOT_EVALUATED.

  python scripts/compare_keywords_text_layer.py --lock <procedure lock>.json --screening-seal <seal>... \
      --pdf-root inputs --baseline output/<a> [--candidate output/<b>] --report scratch/v8/<new>.json
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for entry in (ROOT / "src", ROOT):
    if str(entry) not in sys.path:
        sys.path.insert(0, str(entry))

import unicodedata  # noqa: E402

from benchmark.challengers import keyword_confusables  # noqa: E402
from benchmark.ground_truth_tools import text_layer_reference as tlr  # noqa: E402
from ocr_keywords.alias_map import find_alias_candidates  # noqa: E402
from ocr_keywords.counter import KeywordCounter  # noqa: E402
from scripts import measure_text_layer_diacritics as measure  # noqa: E402
from scripts.run_vlm_challenger import product_texts  # noqa: E402

SCHEMA = "ocr-v8-keyword-text-layer-comparison-v1"


def flat(text: str) -> str:
    return re.sub(r"\s+", " ", text or "").strip()


def counts(text: str, keywords) -> Counter:
    return Counter(keyword for keyword, _, _ in KeywordCounter.iter_occurrences(flat(text), keywords))


def errors(reference: Counter, prediction: Counter) -> dict:
    keys = set(reference) | set(prediction)
    return {k: {"reference": reference[k], "prediction": prediction[k],
                "missing": max(0, reference[k] - prediction[k]), "extra": max(0, prediction[k] - reference[k])}
            for k in keys if reference[k] or prediction[k]}


def review_cells(reference: Counter, prediction_text: str, prediction: Counter, keywords) -> dict:
    """Per keyword: how many missing literal occurrences the review candidates of one page cover."""
    nfc = lambda value: unicodedata.normalize("NFC", value)  # noqa: E731
    text = flat(prediction_text)
    alias = Counter(nfc(c.keyword) for c in find_alias_candidates(text, keywords))
    confusable = Counter(nfc(row["keyword"]) for row in keyword_confusables.find_candidates(text, keywords))
    reference = Counter({nfc(k): v for k, v in reference.items()})
    prediction = Counter({nfc(k): v for k, v in prediction.items()})
    cells = {}
    for keyword in set(alias) | set(confusable) | {k for k in reference if reference[k] > prediction[k]}:
        missing = max(0, reference[keyword] - prediction[keyword])
        by_alias = min(missing, alias[keyword])
        by_confusable = min(missing - by_alias, confusable[keyword])
        cells[keyword] = {"missing_literal": missing, "covered_by_alias": by_alias,
                          "covered_by_confusable": by_confusable,
                          "missing_after_review": missing - by_alias - by_confusable,
                          "alias_candidates_without_reference": alias[keyword] - by_alias,
                          "confusable_candidates_without_reference": confusable[keyword] - by_confusable}
    return cells


def compare(lock_path: Path, seals, pdf_root: Path, outputs: dict, keywords) -> dict:
    lock = json.loads(lock_path.read_bytes())
    accepted = measure.accepted_screenings(lock, seals)
    inventory_path = ROOT / lock["inventory"]["path"]
    inventory = {d["sha256"]: d for d in json.loads(inventory_path.read_bytes())["documents"]}
    runs = {name: measure.batch_documents(path) for name, path in outputs.items()}
    totals = {name: Counter() for name in outputs}
    per_keyword = {name: defaultdict(Counter) for name in outputs}
    review_totals = {name: Counter() for name in outputs}
    review_keywords = {name: defaultdict(Counter) for name in outputs}
    effects = Counter()
    pages_scored, left_out = 0, []
    for sha, screening in sorted(accepted.items(), key=lambda item: item[1]["pdf"]):
        if any(sha not in run or not run[sha]["completed"] for run in runs.values()):
            left_out.append(screening["pdf"])
            continue
        pdf_bytes = (pdf_root / screening["pdf"]).read_bytes()
        texts = {name: product_texts(json.loads((outputs[name] / runs[name][sha]["id"] / "extraction.json").read_bytes()))
                 for name in outputs}
        for record in inventory[sha]["page_records"]:
            if record["status"] != "CANDIDATE":
                continue
            page = record["page"]
            lines, _ = measure.reference_lines(tlr.page_units(pdf_bytes, page))
            reference = counts("\n".join(line["text"] for line in lines), keywords)
            cells = {}
            for name in outputs:
                cells[name] = errors(reference, counts(texts[name].get(page, ""), keywords))
                for keyword, row in cells[name].items():
                    totals[name].update(reference=row["reference"], prediction=row["prediction"],
                                        missing=row["missing"], extra=row["extra"])
                    per_keyword[name][keyword].update(missing=row["missing"], extra=row["extra"],
                                                      reference=row["reference"])
                predicted = Counter({k: v["prediction"] for k, v in cells[name].items()})
                for keyword, row in review_cells(reference, texts[name].get(page, ""), predicted, keywords).items():
                    review_totals[name].update(row)
                    review_keywords[name][keyword].update(row)
            if len(outputs) == 2:
                base, cand = (cells[name] for name in outputs)
                for keyword in set(base) | set(cand):
                    b = sum(base.get(keyword, {}).get(k, 0) for k in ("missing", "extra"))
                    c = sum(cand.get(keyword, {}).get(k, 0) for k in ("missing", "extra"))
                    effects["fixed" if c < b else "harmed" if c > b else "same_error" if b else "both_right"] += 1
            pages_scored += 1
    return {"schema_version": SCHEMA, "quality_acceptance": "NOT_EVALUATED", "counting_policy": "literal_v1",
            "reference_kind": "screened development text layer, visible words, lock v8 reference text (not keyword GT)",
            "outputs": {k: v.as_posix() for k, v in outputs.items()}, "pages": pages_scored, "pdfs_left_out": left_out,
            "totals": {k: dict(v) for k, v in totals.items()},
            "per_keyword": {name: {k: dict(v) for k, v in sorted(rows.items()) if v["missing"] or v["extra"]}
                            for name, rows in per_keyword.items()},
            "paired_page_keyword_effects": dict(effects) if len(outputs) == 2 else None,
            "review_tier": {name: {"methods": ["ocr_keywords.alias_map.find_alias_candidates",
                                               keyword_confusables.METHOD],
                                   "totals": dict(review_totals[name]),
                                   "per_keyword": {k: dict(v) for k, v in sorted(review_keywords[name].items())}}
                            for name in outputs}}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--lock", type=Path, required=True)
    parser.add_argument("--screening-seal", type=Path, nargs="+", required=True)
    parser.add_argument("--pdf-root", type=Path, required=True)
    parser.add_argument("--baseline", type=Path, required=True)
    parser.add_argument("--candidate", type=Path)
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args(argv)
    if args.report.exists():
        parser.error(f"{args.report} exists; reports are never overwritten")
    snapshot = json.loads((args.baseline / "keyword_dictionary.snapshot.json").read_bytes())
    keywords = [row["keyword"] for row in snapshot["canonical_keywords"]]
    outputs = {"baseline": args.baseline, **({"candidate": args.candidate} if args.candidate else {})}
    report = compare(args.lock, args.screening_seal, args.pdf_root, outputs, keywords)
    report["keyword_snapshot_sha256"] = snapshot.get("snapshot_sha256")
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    summary = {k: report[k] for k in ("pages", "totals", "paired_page_keyword_effects")}
    summary["review_tier"] = {name: tier["totals"] for name, tier in report["review_tier"].items()}
    print(json.dumps(summary, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
