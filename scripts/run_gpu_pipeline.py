"""Run the V6.3 GPU batch through its receipt and publication gates.

Each new invocation uses a new output directory. To continue a run, pass
--output <that directory> --resume. Historical output/v63 is never rebased.
All PDFs in --input enter the frozen input manifest, including failures.
"""
from __future__ import annotations

import argparse
from datetime import datetime
from pathlib import Path
import sys
import uuid

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))
sys.path.insert(0, str(PROJECT_ROOT))


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, allow_abbrev=False)
    parser.add_argument("--input", type=Path, default=PROJECT_ROOT / "inputs")
    parser.add_argument("--output", type=Path)
    parser.add_argument("--resume", action="store_true")
    args, remaining = parser.parse_known_args(argv)
    if args.resume and args.output is None:
        parser.error("--resume requires --output pointing to the original run")
    output = args.output or (PROJECT_ROOT / "output" /
        ("gpu-" + datetime.now().strftime("%Y%m%d-%H%M%S") + "-" + uuid.uuid4().hex[:8]))
    command = ["--input", str(args.input), "--output", str(output), *remaining]
    if args.resume:
        command.append("--resume")
    print(f"GPU batch output: {output}", flush=True)
    # The application owns identity, full-page CUDA evidence, completion,
    # hashes, validation, failed rows and durable matrix publication.
    from ocr_pipeline.cli import main_v63
    try:
        code = main_v63(True, command)
    except Exception as exc:
        print(f"GPU batch failed: {type(exc).__name__}: {exc}", file=sys.stderr, flush=True)
        return 1
    if code != 0:
        print("GPU batch incomplete; inspect batch_report.json and logs.", file=sys.stderr, flush=True)
        return code
    print(f"All documents passed the artifact gates. Output: {output}", flush=True)
    print("OCR accuracy and human quality acceptance: NOT_EVALUATED.", flush=True)
    return 0


if __name__ == "__main__":
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)
    sys.exit(main())
