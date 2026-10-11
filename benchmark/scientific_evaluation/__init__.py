"""
V5.0 Scientific Evaluation Suite.
Academic Benchmark & Evaluation Framework adhering to ICDAR, DocEng, and IEEE standards,
and conforming to RESEARCH_PROTOCOL_V5.md.
"""

from .teds_metric import compute_teds, compute_teds_struct, evaluate_table_collection, TableTree
from .dla_metric import compute_dla_map, compute_iou, evaluate_coco_class_ap, compute_class_ap, box_xywh_to_xyxy
from .ocr_metric import compute_cer, compute_wer, compute_der, compute_cer_detailed, compute_wer_detailed, compute_der_detailed
from .reading_order_metric import compute_reading_order, compute_reading_order_spearman, compute_reading_order_metrics
from .numeric_metric import compute_numeric_metrics, NumericExactMatcher
from .markdown_evaluator import evaluate_final_markdown, parse_markdown_artifacts, evaluate_multipage_markdown
from .environment_profiler import capture_environment_metadata, verify_cpu_latency_compliance, TARGET_CPU_LIMITS
from .ablation_runner import compute_bootstrap_ci, run_synthetic_ablation_comparison
from .latex_generator import generate_latex_comparison_table, generate_latex_ablation_table

__all__ = [
    "compute_teds",
    "compute_teds_struct",
    "evaluate_table_collection",
    "TableTree",
    "compute_dla_map",
    "compute_iou",
    "evaluate_coco_class_ap",
    "compute_class_ap",
    "box_xywh_to_xyxy",
    "compute_cer",
    "compute_wer",
    "compute_der",
    "compute_cer_detailed",
    "compute_wer_detailed",
    "compute_der_detailed",
    "compute_reading_order",
    "compute_reading_order_spearman",
    "compute_reading_order_metrics",
    "compute_numeric_metrics",
    "NumericExactMatcher",
    "evaluate_final_markdown",
    "parse_markdown_artifacts",
    "evaluate_multipage_markdown",
    "capture_environment_metadata",
    "verify_cpu_latency_compliance",
    "TARGET_CPU_LIMITS",
    "compute_bootstrap_ci",
    "run_synthetic_ablation_comparison",
    "generate_latex_comparison_table",
    "generate_latex_ablation_table",
]
