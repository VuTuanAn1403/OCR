"""Recount verified unified output, or create a new analysis batch."""
import argparse
import json
from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

import src.ocr
from src.ocr.runtime.paths import output_dir


def main():
    if sys.platform == "win32":
        for stream in (sys.stdout, sys.stderr):
            if hasattr(stream, "reconfigure"):
                stream.reconfigure(encoding="utf-8", errors="replace")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("target", help="Document output directory or document ID inside the output directory")
    parser.add_argument("--keywords-file", help="UTF-8 text file, one keyword per line (default: config/keywords.txt)")
    parser.add_argument("--output", type=Path, help="New analysis directory; required when changing the dictionary")
    parser.add_argument("--keyword-set-version", default="v1")
    args = parser.parse_args()
    target = Path(args.target).expanduser()
    if not target.is_dir():
        target = output_dir() / args.target
        if not target.is_dir() and not target.is_absolute():
            target = PROJECT_ROOT / target
    try:
        if args.output:
            from ocr_pipeline.analysis_run import run_analysis
            from ocr_runtime.paths import default_keywords_path
            result = run_analysis([target], args.output, args.keywords_file or default_keywords_path(),
                                  keyword_set_version=args.keyword_set_version)
            return 0 if result["documents"] and all(r.get("outcome") == "SUCCEEDED" for r in result["documents"]) else 1
        if args.keywords_file:
            raise ValueError("Changing keywords requires --output for a new verified analysis run")
        batch = target if (target / "batch_state.sqlite").is_file() else target.parent
        if not (batch / "batch_state.sqlite").is_file():
            raise ValueError("Verified unified batch required. Use --output to analyze an extraction with valid OCR receipts")
        from ocr_pipeline.recount import recount_batch
        result = recount_batch(batch)
        print(f"Unified batch recounted and published: {result['matrix']}")
        return 0
    except (OSError, ValueError) as exc:
        parser.exit(1, f"[ERROR] {exc}\n")


if __name__ == "__main__":
    raise SystemExit(main())
