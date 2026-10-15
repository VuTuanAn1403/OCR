"""Collect source metadata, lock company splits, and prepare unannotated drafts."""
import argparse
import json
from pathlib import Path

from src.ocr.collect.catalog import collect_sources, lock_company_splits, prepare_gt_drafts


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    subs = parser.add_subparsers(dest="command", required=True)
    collect = subs.add_parser("sources")
    collect.add_argument("--input", required=True)
    collect.add_argument("--metadata", help="Verified metadata JSON keyed by relative PDF path")
    collect.add_argument("--output", required=True)
    lock = subs.add_parser("splits")
    lock.add_argument("--sources", required=True)
    lock.add_argument("--assignments", required=True)
    lock.add_argument("--output", required=True)
    draft = subs.add_parser("drafts")
    draft.add_argument("--sources", required=True)
    draft.add_argument("--splits", required=True)
    draft.add_argument("--output", required=True)
    draft.add_argument("--pages", type=int, default=50)
    draft.add_argument("--seed", type=int, default=42)
    draft.add_argument("--source-root", help="PDF root override for a relocated source inventory")
    args = parser.parse_args()
    try:
        if args.command == "sources":
            metadata = json.loads(Path(args.metadata).read_text(encoding="utf-8")) if args.metadata else None
            result = collect_sources(Path(args.input), Path(args.output), metadata)
            print(f"Collected {len(result)} source PDFs; unknown metadata requires human verification")
        elif args.command == "splits":
            assignments = json.loads(Path(args.assignments).read_text(encoding="utf-8"))
            lock_company_splits(Path(args.sources), assignments, Path(args.output))
            print(f"Locked company splits: {args.output}")
        else:
            result = prepare_gt_drafts(Path(args.sources), Path(args.splits), Path(args.output), pages=args.pages,
                seed=args.seed, source_root=Path(args.source_root) if args.source_root else None)
            print(f"Prepared {result['selected_pages']} UNANNOTATED drafts; these are not ground truth")
    except (OSError, ValueError, TypeError, KeyError) as exc:
        parser.error(str(exc))


if __name__ == "__main__":
    main()
