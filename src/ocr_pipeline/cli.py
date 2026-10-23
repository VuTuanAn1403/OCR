"""One CPU-only application CLI: full-page GPU OCR, recount and analysis."""
import argparse
from pathlib import Path

from ocr_runtime.paths import PROJECT_ROOT, default_keywords_path
from ocr_runtime.config import ConfigError, resolve_config_path
from ocr_runtime.pipeline_policy import BACKEND, PROFILE


def _backend(value):
    if value != BACKEND:
        raise argparse.ArgumentTypeError("Legacy backend was retired. Use the unified pipeline without --backend.")
    return value


def _profile(value):
    if value != PROFILE:
        raise argparse.ArgumentTypeError(f"Historical profiles were retired. Use --profile {PROFILE} or omit --profile.")
    return value


def main(batch=True, argv=None):
    parser = argparse.ArgumentParser(allow_abbrev=False,
        description="Unified OCR: full-page GPU OCR -> Docling -> keyword Excel -> committed matrix. "
                    "One pipeline; legacy profiles/backends are retired.")
    if batch:
        parser.add_argument("--input",type=Path,default=PROJECT_ROOT/"inputs")
    else:
        parser.add_argument("input",type=Path)
    parser.add_argument("--output",type=Path,default=None,help="default: output/v63")
    parser.add_argument("--backend",type=_backend,default=BACKEND,help=argparse.SUPPRESS)
    parser.add_argument("--config",type=Path,default=None,help="argument, OCR_CONFIG_PATH, then config/profiles.yaml")
    parser.add_argument("--profile",type=_profile,default=PROFILE)
    parser.add_argument("--device",choices=("cuda",),default="cuda")
    parser.add_argument("--env-root",type=Path,default=PROJECT_ROOT/".venv-v62")
    parser.add_argument("--keywords-file",type=Path,default=default_keywords_path())
    parser.add_argument("--keyword-set-version",default="v1")
    parser.add_argument("--counting-policy",choices=("literal_v1",),default="literal_v1")
    parser.add_argument("--workers",type=int,choices=(1,),default=1)
    parser.add_argument("--max-attempts",type=int,default=2)
    parser.add_argument("--resume",action="store_true")
    parser.add_argument("--retry-failed",action="store_true")
    parser.add_argument("--force-ocr",action="store_true")
    parser.add_argument("--recount",action="store_true",help="Recount an existing V6.3 batch, preserving its snapshot and matrix")
    if batch:
        parser.add_argument("--analysis-from",type=Path,nargs="+",metavar="SOURCE",
            help="Count keywords on verified V6.3 outputs (batch or document directories) without OCR; "
                 "writes a new analysis batch to --output, sources stay read-only")
    parser.add_argument("--assets",choices=("png","jpeg","none"),default="png")
    parser.add_argument("--output-mode",choices=("compact","legacy"),default="compact")
    args = parser.parse_args(argv)
    if args.max_attempts < 1:
        parser.error("--max-attempts must be positive")
    if getattr(args, "analysis_from", None):
        if args.output is None:
            parser.error("--analysis-from requires an explicit --output for the new analysis run")
        if args.recount or args.force_ocr:
            parser.error("--analysis-from never runs OCR or recounts in place")
        from ocr_pipeline.analysis_run import run_analysis
        result = run_analysis(args.analysis_from, args.output, args.keywords_file,
                              keyword_set_version=args.keyword_set_version, resume=args.resume,
                              retry_failed=args.retry_failed)
        return 1 if not result["documents"] or any(r.get("outcome")!="SUCCEEDED" for r in result["documents"]) else 0
    if args.output is None:
        args.output = PROJECT_ROOT/"output/v63"
    if args.recount:
        from ocr_pipeline.recount import recount_batch
        recount_batch(args.output)
        return 0
    from ocr_keywords.contract import dictionary_snapshot
    dictionary_snapshot(args.keywords_file,args.keyword_set_version)
    from ocr_pipeline.backend import prepare_backend, verify_runtime, GPUProcessor
    try:
        config_path = resolve_config_path(args.config)
        backend = prepare_backend(config_path,args.profile,args.env_root)
    except ConfigError as exc:
        parser.error(str(exc))
    processor = GPUProcessor(backend,assets=args.assets,output_mode=args.output_mode)
    from ocr_pipeline.batch import process_batch
    result = process_batch(args.input,args.output,{"backend":backend,"assets":args.assets,"output_mode":args.output_mode,
        "input_path":str(args.input.resolve()),
        "keyword_set_version":args.keyword_set_version,"counting_policy":args.counting_policy},args.keywords_file,processor,
        resume=args.resume,retry_failed=args.retry_failed,force_ocr=args.force_ocr,max_attempts=args.max_attempts,
        identity_check=lambda:verify_runtime(backend))
    return 1 if not result["documents"] or any(r.get("outcome")!="SUCCEEDED" for r in result["documents"]) else 0


# Stable spelling for existing importers, without a second implementation.
main_v63 = main
