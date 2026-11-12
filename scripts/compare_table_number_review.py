#!/usr/bin/env python3
"""Re-check sealed table-number review items on newer outputs (V8-080).

CPU only, read-only. The sealed review (``build_table_number_review.py seal``) decided, from the page
image, whether each audited number is printed. For every output given, each item is looked up on
its page by number token (``audit_runtime_invariants.numbers``):

* ``in_table``: the number is a token of a cell of a table whose box overlaps one of the item's
  source lines;
* ``visible``: the number is a token of a visible text item whose box overlaps one of the item's
  source lines. Geometry, not ``source_id``: source ranks shift between runs whose accepted line
  sets differ (for example a recognizer change), so an id of the reviewed run may name another line.

For ``TABLE_LOST_A_PRINTED_NUMBER`` (printed, but the table of the reviewed output lacked it) the
number counts as recovered when it is ``in_table``, and as kept when it is at least ``visible``.
For the not-printed outcomes, a number still ``in_table`` remains an unprinted table value. The
sample is an audit worklist, not a random sample: counts never estimate a rate.

  python scripts/compare_table_number_review.py --sheet scratch/v8/table_review/<sheet> \
      --seal scratch/v8/table_review/sealed/<seal>/seal.json --outputs output/<a> output/<b> --report scratch/v8/<new>.json
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for entry in (ROOT / "src", ROOT):
    if str(entry) not in sys.path:
        sys.path.insert(0, str(entry))

from scripts.audit_runtime_invariants import numbers  # noqa: E402
from scripts.build_table_number_review import OUTCOMES, latest  # noqa: E402

SCHEMA = "ocr-v8-table-number-recheck-v1"


def _overlaps(a, b) -> bool:
    return min(a[2], b[2]) > max(a[0], b[0]) and min(a[3], b[3]) > max(a[1], b[1])


def locate(item: dict, page: dict) -> dict:
    lines = [box for box in item.get("line_bboxes") or [] if box]
    in_table = any(item["number"] in numbers(cell.get("text_raw"))
                   for table in page["items"] if table["kind"] == "t" and table.get("bbox")
                   and any(_overlaps(table["bbox"], line) for line in lines)
                   for cell in table.get("cells") or ())
    visible = any(item["number"] in numbers(block.get("text_raw"))
                  for block in page["items"] if block["kind"] == "b" and block.get("bbox")
                  and any(_overlaps(block["bbox"], line) for line in lines))
    return {"in_table": in_table, "visible": visible}


def compare(sheet_dir: Path, seal_path: Path, outputs) -> dict:
    sheet = json.loads((sheet_dir / "sheet.json").read_bytes())
    seal = json.loads(seal_path.read_bytes())
    records = [json.loads(line) for line in (seal_path.parent / seal["sealed_file"]).read_text(encoding="utf-8").splitlines()
               if line.strip()]
    decisions = latest(records)
    items = {item["item_id"]: item for item in sheet["items"]}
    result = {"schema_version": SCHEMA, "quality_acceptance": "NOT_EVALUATED", "seal": seal_path.as_posix(),
              "sealed_sha256": seal["sealed_sha256"], "sample": seal["sample"], "outputs": {}}
    for output in outputs:
        pages, counts, detail = {}, defaultdict(Counter), []
        for item_id, decision in sorted(decisions.items()):
            item = items[item_id]
            outcome = OUTCOMES.get((item["kind"], decision["choice"]), "UNRESOLVED")
            key = (item["document"], item["page"])
            if key not in pages:
                extraction = json.loads((Path(output) / item["document"] / "extraction.json").read_bytes())
                pages.update({(item["document"], p["page"]): p for p in extraction["pages"]})
            found = locate(item, pages[key])
            state = "in_table" if found["in_table"] else "visible_only" if found["visible"] else "absent"
            counts[outcome][state] += 1
            detail.append({"item_id": item_id, "outcome": outcome, "origin": item["origin"], "state": state})
        result["outputs"][Path(output).as_posix()] = {"by_outcome": {k: dict(v) for k, v in counts.items()},
                                                      "items": detail}
    return result


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--sheet", type=Path, required=True)
    parser.add_argument("--seal", type=Path, required=True)
    parser.add_argument("--outputs", type=Path, nargs="+", required=True)
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args(argv)
    if args.report.exists():
        parser.error(f"{args.report} exists; reports are never overwritten")
    report = compare(args.sheet, args.seal, args.outputs)
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    for output, data in report["outputs"].items():
        print(output, json.dumps(data["by_outcome"], ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
