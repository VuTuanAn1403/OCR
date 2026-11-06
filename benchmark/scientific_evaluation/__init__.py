"""Evaluation tools with lazy public exports and isolated optional runtimes."""
from importlib import import_module

_EXPORTS = {
    "teds_metric": ("compute_teds", "compute_teds_struct", "evaluate_table_collection", "TableTree"),
    "dla_metric": ("compute_dla_map", "compute_iou", "evaluate_coco_class_ap", "compute_class_ap", "box_xywh_to_xyxy"),
    "ocr_metric": ("compute_cer", "compute_wer", "compute_der", "compute_cer_detailed", "compute_wer_detailed", "compute_der_detailed"),
    "reading_order_metric": ("compute_reading_order", "compute_reading_order_spearman", "compute_reading_order_metrics"),
    "numeric_metric": ("compute_numeric_metrics", "NumericExactMatcher"),
    "markdown_evaluator": ("evaluate_final_markdown", "parse_markdown_artifacts", "evaluate_multipage_markdown"),
    "environment_profiler": ("capture_environment_metadata", "verify_cpu_latency_compliance", "TARGET_CPU_LIMITS"),
    "ablation_runner": ("compute_bootstrap_ci", "run_synthetic_ablation_comparison"),
    "latex_generator": ("generate_latex_comparison_table", "generate_latex_ablation_table"),
}
_MODULE_BY_EXPORT = {name: module for module, names in _EXPORTS.items() for name in names}


def __getattr__(name):
    module = _MODULE_BY_EXPORT.get(name)
    if module is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    value = getattr(import_module(f".{module}", __name__), name)
    globals()[name] = value
    return value


def __dir__():
    return sorted(set(globals()) | set(__all__))

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
