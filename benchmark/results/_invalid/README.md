# Invalidated Benchmark Artifacts

The artifacts previously in `benchmark/results/` (including `*_ablation_table.tex`) were generated using synthetic multipliers and default baseline assumptions rather than end-to-end ground truth measurements.

Per **PROPOSAL_FIX_ACCURACY_RELIABILITY_PERFORMANCE.md** (Issue R4), these ungrounded results have been officially invalidated and archived.

All future benchmark tables and LaTeX artifacts must be generated strictly from real ground truth datasets (e.g., via `scripts/run_regression.py` and empirical protocol runs).
