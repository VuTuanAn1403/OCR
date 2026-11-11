#!/usr/bin/env python3
"""Carry blind A/B adjudication decisions from one sheet to a rebuilt sheet of the same items.

A sheet is rebuilt when its measurement lock changes but the measured units do not (for
example lock v4 -> v5 on 11/11/2026). A decision moves only when the item exists on both sheets
with the same crop sha256, the same strings A and B and the same side for A in both keys,
so the reviewer's choice means the same thing on the new sheet. Anything else stops the run;
nothing is guessed. The choice, corrected text, reviewer and time are kept; the record gets the
new ``sheet_id`` and ``migrated_from_sheet`` / ``migrated_decision_id`` for provenance.

  python scripts/migrate_adjudication_decisions.py --from-sheet <old dir> --to-sheet <new dir> \
      --decisions <export>.jsonl --out <new dir>/migrated-<old sheet id>.jsonl
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Dict, List

ROOT = Path(__file__).resolve().parents[1]
for entry in (ROOT / "src", ROOT):
    if str(entry) not in sys.path:
        sys.path.insert(0, str(entry))

from scripts.screen_text_layer import read_jsonl, sha256_bytes, write_new  # noqa: E402


def load_sheet(folder: Path):
    sheet = json.loads((folder / "sheet.json").read_bytes())
    key = json.loads((folder / "ab_key.json").read_bytes())["items"]
    return sheet, {item["item_id"]: item for item in sheet["items"]}, key


def migrate(from_sheet: Path, to_sheet: Path, decision_paths: List[Path], skip_kinds=()) -> Dict:
    old_sheet, old_items, old_key = load_sheet(from_sheet)
    new_sheet, new_items, new_key = load_sheet(to_sheet)
    records = read_jsonl(decision_paths)
    problems, moved, skipped = [], [], 0
    for record in sorted(records, key=lambda r: r["item_id"]):
        item_id = record["item_id"]
        where = f"{item_id}"
        if record.get("sheet_id") != old_sheet["sheet_id"]:
            problems.append(f"{where}: decision belongs to sheet {record.get('sheet_id')}, not {old_sheet['sheet_id']}")
            continue
        old, new = old_items.get(item_id), new_items.get(item_id)
        if old is None or new is None:
            problems.append(f"{where}: item missing on the {'old' if old is None else 'new'} sheet")
            continue
        if (old["crop_sha256"], old["a"], old["b"]) != (new["crop_sha256"], new["a"], new["b"]):
            problems.append(f"{where}: crop or strings differ between the sheets")
            continue
        if new.get("kind") in skip_kinds:  # decided under a display the new sheet replaces; to be re-decided
            skipped += 1
            continue
        if old_key[item_id]["A"] != new_key[item_id]["A"]:
            problems.append(f"{where}: side A differs between the sheets")
            continue
        if (record["crop_sha256"], record["a"], record["b"]) != (new["crop_sha256"], new["a"], new["b"]):
            problems.append(f"{where}: the decision was made on other strings or another crop")
            continue
        moved.append({**record, "sheet_id": new_sheet["sheet_id"], "migrated_from_sheet": old_sheet["sheet_id"],
                      "migrated_decision_id": record["decision_id"]})
    if problems:
        raise ValueError(f"{len(problems)} decisions cannot move:\n  " + "\n  ".join(problems[:40]))
    return {"from_sheet": old_sheet["sheet_id"], "to_sheet": new_sheet["sheet_id"], "records": moved,
            "skipped_by_kind": skipped, "skip_kinds": list(skip_kinds)}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--from-sheet", type=Path, required=True)
    parser.add_argument("--to-sheet", type=Path, required=True)
    parser.add_argument("--decisions", type=Path, nargs="+", required=True)
    parser.add_argument("--out", type=Path, required=True, help="New JSONL (never overwritten)")
    parser.add_argument("--skip-kind", action="append", default=[],
                        help="Leave items of this kind on the new sheet undecided, e.g. ONE_SIDE_EMPTY")
    args = parser.parse_args(argv)
    result = migrate(args.from_sheet, args.to_sheet, args.decisions, tuple(args.skip_kind))
    data = "".join(json.dumps(r, ensure_ascii=False, sort_keys=True) + "\n" for r in result["records"]).encode("utf-8")
    write_new(args.out, data)
    print(f"{len(result['records'])} decisions moved, {result['skipped_by_kind']} left to re-decide "
          f"{result['from_sheet']} -> {result['to_sheet']}: "
          f"{args.out} sha256 {sha256_bytes(data)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
