"""Command facade: V6.3 by default (`ocr_pipeline.cli`); historical profiles,
non-V6.3 configs and `--backend legacy` keep the frozen legacy CLI.

Precedence (P12): `--backend`, then the `pipeline` a `--config` file declares,
then the historical rules (profile name, "profiles-v63" in the file name) for
files that declare nothing."""
import argparse
from pathlib import Path
import sys


def use_v63(argv):
    probe=argparse.ArgumentParser(add_help=False)
    for name in ("backend","profile","config"):
        probe.add_argument("--"+name)
    parsed,_=probe.parse_known_args(argv)
    if parsed.backend:
        return parsed.backend != "legacy"
    if parsed.config and Path(parsed.config).expanduser().is_file():
        from ocr_runtime.config import declared_pipeline
        declared = declared_pipeline(parsed.config)
        if declared is not None:
            return declared == "v6.3"
    historical = parsed.profile and parsed.profile != "unified_gpu_full_ocr"
    configured = parsed.config and "profiles-v63" not in parsed.config
    return not (historical or configured)


def main(batch=True, argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    if not use_v63(argv):
        argv=[a for a in argv if a!="--backend=legacy"]
        if "--backend" in argv:
            index = argv.index("--backend")
            del argv[index:index+2]
        sys.argv = [sys.argv[0],*argv]
        if batch:
            from src.ocr.cli.batch_runner import main as legacy
        else:
            from src.ocr.cli.run_ocr import main as legacy
        return legacy()
    from ocr_pipeline.cli import main_v63
    return main_v63(batch, argv)


def run_one():
    return main(False)


def run_batch():
    return main(True)
