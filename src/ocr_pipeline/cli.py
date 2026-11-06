"""One CPU-only application CLI: full-page GPU OCR, recount and analysis."""
import argparse
from pathlib import Path

from ocr_runtime.paths import PROJECT_ROOT, default_keywords_path
from ocr_runtime.config import ConfigError, resolve_config_path
from ocr_runtime.pipeline_policy import BACKEND, PROFILE
from ocr_runtime.version import PIPELINE, PIPELINE_VERSION
from ocr_keywords.contract import DEFAULT_KEYWORD_SET_VERSION


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
    parser.add_argument("--version", action="version", version=f"OCR PDF {PIPELINE} ({PIPELINE_VERSION})")
    if batch:
        parser.add_argument("--input",type=Path,default=PROJECT_ROOT/"inputs")
    else:
        parser.add_argument("input",type=Path)
    default_output = PROJECT_ROOT / "output" / PIPELINE.replace(".", "")
    parser.add_argument("--output",type=Path,default=None,help=f"default: output/{default_output.name}")
    parser.add_argument("--backend",type=_backend,default=BACKEND,help=argparse.SUPPRESS)
    parser.add_argument("--config",type=Path,default=None,help="argument, OCR_CONFIG_PATH, then config/profiles.yaml")
    parser.add_argument("--profile",type=_profile,default=PROFILE)
    parser.add_argument("--device",choices=("cuda",),default="cuda")
    parser.add_argument("--env-root",type=Path,default=PROJECT_ROOT/".venv-v62")
    parser.add_argument("--keywords-file",type=Path,default=default_keywords_path())
    parser.add_argument("--keyword-set-version",default=None,
                        help="Dictionary set version tag (default: auto-derived from custom filename, or v1)")
    parser.add_argument("--counting-policy",choices=("literal_v1",),default="literal_v1")
    parser.add_argument("--workers",type=int,choices=(1,),default=1)
    parser.add_argument("--max-attempts",type=int,default=2)
    parser.add_argument("--resume",action="store_true")
    parser.add_argument("--retry-failed",action="store_true")
    parser.add_argument("--force-ocr",action="store_true")
    parser.add_argument("--recount",action="store_true",help="Recount a verified batch, preserving its snapshot and matrix")
    if batch:
        source_mode = parser.add_mutually_exclusive_group()
        source_mode.add_argument("--analysis-from",type=Path,nargs="+",metavar="SOURCE",
            help="Count keywords on verified extraction outputs (batch or document directories) without OCR; "
                 "writes a new analysis batch to --output, sources stay read-only")
        source_mode.add_argument("--review-from",type=Path,nargs="+",metavar="SOURCE",
            help="Export source image crops and OCR evidence to a new operator review packet")
        source_mode.add_argument("--table-stitch-from", type=Path, metavar="DOCUMENT",
            help="Preview a proposed table chain from a verified extraction without OCR")
        parser.add_argument("--table-stitch-plan", type=Path, metavar="PLAN",
                            help="Draft plan for --table-stitch-from")
        parser.add_argument("--review-limit",type=int,default=100,help="Maximum review items rendered per packet")
        parser.add_argument("--review-offset",type=int,default=0,help="Skip this many items in the frozen review order")
    parser.add_argument("--assets",choices=("png","jpeg","none"),default="png")
    parser.add_argument("--output-mode",choices=("compact","legacy"),default="compact")
    parser.add_argument("--alias-decisions", type=Path, default=None,
                        help="JSON bundle of operator review decisions for Tier 2 keyword reconciliation")
    rule_mode = parser.add_mutually_exclusive_group()
    rule_mode.add_argument("--alias-rules", type=Path, help="Global approved/disallowed alias rules; default: bundled rules with the default dictionary")
    rule_mode.add_argument("--no-alias-rules", action="store_true", help="Disable global alias rules for this new run")
    args = parser.parse_args(argv)
    if (args.alias_rules is not None or args.no_alias_rules) and (args.recount or getattr(args, "review_from", None) or getattr(args, "table_stitch_from", None)):
        parser.error("Alias rule changes require a new OCR or analysis output")
    if args.alias_decisions is not None and not getattr(args, "analysis_from", None):
        parser.error("--alias-decisions requires --analysis-from and an explicit analysis output")
    if args.max_attempts < 1:
        parser.error("--max-attempts must be positive")
    if getattr(args, "table_stitch_from", None):
        if not args.output or not args.table_stitch_plan or args.recount or args.force_ocr or args.resume or args.retry_failed:
            parser.error("--table-stitch-from requires a draft plan and new --output, without resume, recount or OCR flags")
        from ocr_pipeline.table_stitch_preview import run_preview
        try:
            result = run_preview(args.table_stitch_from, args.table_stitch_plan, args.output)
        except (OSError, ValueError, KeyError, TypeError) as exc:
            parser.error(str(exc))
        print(f"Table preview: {result['table']['observed_source_cells']} source cells. {args.output}")
        return 0
    if getattr(args, "table_stitch_plan", None):
        parser.error("--table-stitch-plan requires --table-stitch-from")
    if getattr(args, "review_from", None):
        if args.output is None or args.recount or args.force_ocr or args.resume or args.retry_failed:
            parser.error("--review-from requires a new explicit --output and cannot resume, recount or force OCR")
        from ocr_pipeline.review_packet import run_review
        try:
            report = run_review(args.review_from, args.output, args.keywords_file,
                                limit=args.review_limit, offset=args.review_offset,
                                keyword_set_version=args.keyword_set_version)
        except (OSError, ValueError, KeyError, TypeError) as exc:
            parser.error(str(exc))
        print(f"Review packet: {report['selected_items']} of {report['total_queue_items']} items. {args.output}")
        return 0
    if getattr(args, "analysis_from", None):
        if args.output is None:
            parser.error("--analysis-from requires an explicit --output for the new analysis run")
        if args.recount or args.force_ocr:
            parser.error("--analysis-from never runs OCR or recounts in place")
        from ocr_pipeline.analysis_run import run_analysis
        from ocr_pipeline.alias_finalization import selected_rules_path
        version = args.keyword_set_version
        if version is None:
            if args.keywords_file and Path(args.keywords_file).resolve() != default_keywords_path().resolve():
                version = f"custom-{Path(args.keywords_file).stem}"
            else:
                version = DEFAULT_KEYWORD_SET_VERSION
        result = run_analysis(args.analysis_from, args.output, args.keywords_file,
                              keyword_set_version=version, resume=args.resume,
                              retry_failed=args.retry_failed, alias_decisions=args.alias_decisions,
                              alias_rules=selected_rules_path(args.alias_rules, args.no_alias_rules, args.keywords_file))
        return 1 if not result["documents"] or any(r.get("outcome")!="SUCCEEDED" for r in result["documents"]) else 0
    if args.output is None:
        args.output = default_output
    if args.recount:
        from ocr_pipeline.recount import recount_batch
        recount_batch(args.output)
        return 0
    from ocr_keywords.contract import dictionary_snapshot
    version = args.keyword_set_version
    if version is None:
        if args.keywords_file and Path(args.keywords_file).resolve() != default_keywords_path().resolve():
            version = f"custom-{Path(args.keywords_file).stem}"
        else:
            version = DEFAULT_KEYWORD_SET_VERSION
    snapshot = dictionary_snapshot(args.keywords_file, version)
    from ocr_pipeline.alias_finalization import AliasFinalizingProcessor, selected_rules_path
    from ocr_pipeline.analysis_run import AnalysisProcessor
    rule_path = selected_rules_path(args.alias_rules, args.no_alias_rules, args.keywords_file)
    policy = AnalysisProcessor(alias_rules=rule_path, dictionary=snapshot)
    from ocr_pipeline.backend import prepare_backend, verify_runtime, GPUProcessor
    try:
        config_path = resolve_config_path(args.config)
        backend = prepare_backend(config_path,args.profile,args.env_root)
    except ConfigError as exc:
        parser.error(str(exc))
    processor = GPUProcessor(backend,assets=args.assets,output_mode=args.output_mode)
    if policy.rules_snapshot is not None:
        processor = AliasFinalizingProcessor(processor, policy)
    from ocr_pipeline.batch import process_batch
    result = process_batch(args.input,args.output,{"backend":backend,"assets":args.assets,"output_mode":args.output_mode,
        "input_path":str(args.input.resolve()),
        "keyword_set_version":version,"counting_policy":args.counting_policy,
        **({"alias_rules": policy.rules_snapshot} if policy.rules_snapshot is not None else {})},args.keywords_file,processor,
        resume=args.resume,retry_failed=args.retry_failed,force_ocr=args.force_ocr,max_attempts=args.max_attempts,
        identity_check=lambda:(verify_runtime(backend), policy.verify_decision_source()))
    return 1 if not result["documents"] or any(r.get("outcome")!="SUCCEEDED" for r in result["documents"]) else 0


# Stable spelling for existing importers, without a second implementation.
main_v63 = main
