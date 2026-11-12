#!/usr/bin/env python3
"""Page-level diagnostic of VLM page_text against production on screened pages (V8-090).

CPU only, read-only. For each VLM record of an experiment it takes the production page text
(the exact text the run hashed, ``run_vlm_challenger.product_texts``; its sha256 must equal the
record's ``product_text_sha256``) and, on PDFs whose text-layer screening was ACCEPTED, the
text layer of the page as reference. Both are scored with the locked metric functions
(``compute_dser_strict_detailed``, ``compute_cer_detailed``) after collapsing whitespace.

Page-level alignment is sensitive to reading order, so these are diagnostics: ``fixed`` = the VLM
page has fewer DSER errors than production, ``harmed`` = more. Pages where the VLM repeats its
prompt, or returns nothing, are counted apart. The reference is the development text layer,
not independent GT: quality stays NOT_EVALUATED, decision INCONCLUSIVE. Nothing is written back
to production.

  python scripts/compare_vlm_pages.py --experiment scratch/benchmarks/<EXP> --output output/<run> \
      --pdf-root inputs --screening-seal <seal>... --report scratch/v8/<new>.json
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for entry in (ROOT / "src", ROOT):
    if str(entry) not in sys.path:
        sys.path.insert(0, str(entry))

from benchmark.challengers.vlm.adapter import PROMPTS  # noqa: E402
from benchmark.scientific_evaluation.ocr_metric import compute_cer_detailed, compute_dser_strict_detailed  # noqa: E402
from scripts.run_vlm_challenger import product_texts  # noqa: E402

SCHEMA = "ocr-v8-vlm-page-comparison-v1"
ECHO_MARKERS = ("giữ đúng dấu tiếng việt", "không dịch", "không tóm tắt", "không sửa", "theo từng dòng",
                "do not translate", "line by line", "keeping every diacritic")


def flat(text: str) -> str:
    return re.sub(r"\s+", " ", text or "").strip()


def classify(vlm_text: str) -> str:
    text = flat(vlm_text)
    if not text:
        return "EMPTY"
    folded = text.casefold()
    # The model may paraphrase its instruction; two of its distinctive phrases mark an echo.
    if sum(marker in folded for marker in ECHO_MARKERS) >= 2 or any(flat(p)[:60] in text for p in PROMPTS.values()):
        return "PROMPT_ECHO"
    return "TEXT"


def score(reference: str, prediction: str) -> dict:
    strict = compute_dser_strict_detailed(reference, prediction)
    cer = compute_cer_detailed(reference, prediction)
    return {"dser_errors": strict["dser_errors"], "ref_slots": strict["ref_slots"],
            "char_errors": cer["substitutions"] + cer["deletions"] + cer["insertions"],
            "ref_chars": cer["reference_length"]}


def compare(experiment: Path, output: Path, pdf_root: Path, accepted_pdfs: set) -> dict:
    import pymupdf

    kinds, effects, totals = Counter(), Counter(), Counter()
    pages = []
    for path in sorted((experiment / "predictions").glob("*.jsonl")):
        document = path.stem
        texts = product_texts(json.loads((output / document / "extraction.json").read_bytes()))
        records = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
        pdf_name = f"{document}.pdf"
        with pymupdf.open(pdf_root / pdf_name) as pdf:
            for record in records:
                page = record["physical_page"]
                product = texts.get(page, "")
                if hashlib.sha256(product.encode("utf-8")).hexdigest() != record.get("product_text_sha256"):
                    raise ValueError(f"{document} p{page}: production text differs from the one the run hashed")
                kind = "MISSING_OUTPUT" if record["status"] == "MISSING_OUTPUT" else classify(record.get("text_raw"))
                kinds[kind] += 1
                row = {"document": document, "page": page, "kind": kind, "reasons": record.get("selection_reasons")}
                if pdf_name in accepted_pdfs:
                    reference = flat(pdf[page - 1].get_text())
                    base = score(reference, flat(product))
                    cand = score(reference, flat(record.get("text_raw") or ""))
                    row.update(reference_kind="screened_text_layer", production=base, vlm=cand)
                    if base["ref_slots"]:
                        totals.update(pages=1, ref_slots=base["ref_slots"], production_dser=base["dser_errors"],
                                      vlm_dser=cand["dser_errors"], ref_chars=base["ref_chars"],
                                      production_chars=base["char_errors"], vlm_chars=cand["char_errors"])
                        effects["fixed" if cand["dser_errors"] < base["dser_errors"] else "harmed"
                                if cand["dser_errors"] > base["dser_errors"] else "same"] += 1
                pages.append(row)
    return {"schema_version": SCHEMA, "quality_acceptance": "NOT_EVALUATED", "decision_options": ["INCONCLUSIVE"],
            "experiment": experiment.as_posix(), "output": output.as_posix(),
            "reference_kind": "screened development text layer, page order (diagnostic, not GT)",
            "pages": len(pages), "kinds": dict(kinds), "scored_effects": dict(effects), "scored_totals": dict(totals),
            "rows": pages}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--experiment", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--pdf-root", type=Path, required=True)
    parser.add_argument("--screening-seal", type=Path, nargs="+", required=True)
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args(argv)
    if args.report.exists():
        parser.error(f"{args.report} exists; reports are never overwritten")
    accepted = set()
    for seal in args.screening_seal:
        report = json.loads(seal.read_bytes())
        if (report.get("verdict") or {}).get("status") == "ACCEPTED":
            accepted.add(report["pdf"])
    result = compare(args.experiment, args.output, args.pdf_root, accepted)
    result["accepted_pdfs"] = sorted(accepted)
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(result, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(json.dumps({"pages": result["pages"], "kinds": result["kinds"], "scored_effects": result["scored_effects"],
                      "scored_totals": result["scored_totals"]}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
