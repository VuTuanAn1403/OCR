"""
LaTeX Table Generator for Academic Publications (Overleaf & IEEE/Springer/ACM format).
"""

from typing import List, Dict, Any, Optional


def generate_latex_comparison_table(
    methods_data: List[Dict[str, Any]],
    caption: str = "Performance comparison between proposed V5.0 and baseline methods on Vietnamese Document Benchmark",
    label: str = "tab:benchmark_comparison"
) -> str:
    """
    Generates a publication-grade LaTeX table with booktabs format.
    methods_data: list of dicts with keys:
    {"name": "...", "map50": ..., "teds": ..., "cer": ..., "der": ..., "pps": ..., "time_per_page": ...}
    """
    latex = []
    latex.append(r"\begin{table*}[t]")
    latex.append(r"\centering")
    latex.append(f"\\caption{{{caption}}}")
    latex.append(f"\\label{{{label}}}")
    latex.append(r"\begin{tabular}{lcccccc}")
    latex.append(r"\toprule")
    latex.append(r"\textbf{Method} & \textbf{DLA mAP@50 $\uparrow$} & \textbf{TSR TEDS $\uparrow$} & \textbf{CER $\downarrow$} & \textbf{DER $\downarrow$} & \textbf{Throughput (PPS) $\uparrow$} & \textbf{Avg Latency (s) $\downarrow$} \\")
    latex.append(r"\midrule")

    for item in methods_data:
        name = item.get("name", "")
        is_ours = "V5.0" in name or "Ours" in name
        fmt_name = f"\\textbf{{{name}}}" if is_ours else name

        map_val = f"{item.get('map50', 0.0):.3f}"
        teds_val = f"{item.get('teds', 0.0):.3f}"
        cer_val = f"{item.get('cer', 0.0):.3f}"
        der_val = f"{item.get('der', 0.0):.3f}"
        pps_val = f"{item.get('pps', 0.0):.2f}"
        time_val = f"{item.get('time_per_page', 0.0):.2f}s"

        if is_ours:
            map_val = f"\\textbf{{{map_val}}}"
            teds_val = f"\\textbf{{{teds_val}}}"
            cer_val = f"\\textbf{{{cer_val}}}"
            der_val = f"\\textbf{{{der_val}}}"
            pps_val = f"\\textbf{{{pps_val}}}"
            time_val = f"\\textbf{{{time_val}}}"

        row = f"{fmt_name} & {map_val} & {teds_val} & {cer_val} & {der_val} & {pps_val} & {time_val} \\\\"
        latex.append(row)

    latex.append(r"\bottomrule")
    latex.append(r"\end{tabular}")
    latex.append(r"\end{table*}")
    return "\n".join(latex)


def generate_latex_ablation_table(
    ablation_data: List[Dict[str, Any]],
    caption: str = "Ablation study on architectural components of V5.0",
    label: str = "tab:ablation_study"
) -> str:
    """
    Generates LaTeX table for ablation studies.
    """
    latex = []
    latex.append(r"\begin{table}[htbp]")
    latex.append(r"\centering")
    latex.append(f"\\caption{{{caption}}}")
    latex.append(f"\\label{{{label}}}")
    latex.append(r"\begin{tabular}{lcccc}")
    latex.append(r"\toprule")
    latex.append(r"\textbf{Configuration} & \textbf{mAP@50 $\uparrow$} & \textbf{TEDS $\uparrow$} & \textbf{CER $\downarrow$} & \textbf{Time/Page (s) $\downarrow$} \\")
    latex.append(r"\midrule")

    for item in ablation_data:
        cfg = item.get("config") or item.get("name", "")
        m = f"{item.get('map50', 0.0):.3f}"
        t = f"{item.get('teds', 0.0):.3f}"
        c = f"{item.get('cer', 0.0):.3f}"
        sec = item.get("sec_per_page") if "sec_per_page" in item else item.get("time", 0.0)
        s = f"{float(sec):.2f}s"
        latex.append(f"{cfg} & {m} & {t} & {c} & {s} \\\\")

    latex.append(r"\bottomrule")
    latex.append(r"\end{tabular}")
    latex.append(r"\end{table}")
    return "\n".join(latex)
