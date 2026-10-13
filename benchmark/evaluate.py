import sys

# Reconfigure existing streams without replacing pytest's capture wrappers.
for stream in (sys.stdout, sys.stderr):
    if hasattr(stream, "reconfigure"):
        stream.reconfigure(encoding="utf-8", errors="replace")

import os
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import re
import json
import argparse
import unicodedata
from typing import List, Dict, Tuple, Optional, Any
from tabulate import tabulate

from src.ocr.domain.models.accuracy import AccuracyReport, PageAccuracyReport

VIETNAMESE_DIACRITIC_CHARS = set(
    "ăâđêôơưáàảãạắằẳẵặấầẩẫậéèẻẽẹếềểễệíìỉĩịóòỏõọốồổỗộớờởỡợúùủũụứừửữựýỳỷỹỵ"
    "ĂÂĐÊÔƠƯÁÀẢÃẠẮẰẲẴẶẤẦẨẪẬÉÈẺẼẸẾỀỂỄỆÍÌỈĨỊÓÒỎÕỌỐỒỔỖỘỚỜỞỠỢÚÙỦŨỤỨỪỬỮỰÝỲỶỸỴ"
)

def normalize_evaluation_text(text: str) -> str:
    """Normalizes Unicode NFC, collapses non-breaking/multiple whitespaces, strips synthetic markdown markers."""
    if not text:
        return ""
    text = unicodedata.normalize("NFC", text)
    # Remove synthetic page header: "# Trang 1", "## Trang 11", etc.
    text = re.sub(r"^#+\s*Trang\s+\d+.*$", "", text, flags=re.MULTILINE)
    # Remove markdown header/footer tags or formatting lines
    text = re.sub(r"^>\s*\*{1,2}(?:Header|Footer)\*{1,2}:\s*", "", text, flags=re.MULTILINE)
    text = re.sub(r"^#+\s*", "", text, flags=re.MULTILINE)
    text = re.sub(r"^---\s*$", "", text, flags=re.MULTILINE)
    # Remove table separator lines e.g. "| --- | --- |"
    text = re.sub(r"^\|\s*[-:\s|]+\|\s*$", "", text, flags=re.MULTILINE)

    # Collapse multiple whitespaces and empty lines, and normalize table border pipes
    raw_lines = [re.sub(r"\s+", " ", line).strip() for line in text.splitlines()]
    lines = []
    for l in raw_lines:
        if not l:
            continue
        # Strip outer table pipes for uniform text comparison with reference
        if l.startswith("|") and l.endswith("|"):
            l = l[1:-1].strip()
        lines.append(l)

    return "\n".join(lines)

def levenshtein_distance(s1: List[Any], s2: List[Any]) -> int:
    """Computes Levenshtein distance between two sequences with O(min(N,M)) space."""
    if len(s1) < len(s2):
        return levenshtein_distance(s2, s1)
    if len(s2) == 0:
        return len(s1)

    previous_row = list(range(len(s2) + 1))
    for i, c1 in enumerate(s1):
        current_row = [i + 1] + [0] * len(s2)
        for j, c2 in enumerate(s2):
            insertions = previous_row[j + 1] + 1
            deletions = current_row[j] + 1
            substitutions = previous_row[j] + (c1 != c2)
            current_row[j + 1] = min(insertions, deletions, substitutions)
        previous_row = current_row

    return previous_row[-1]

def compute_cer(reference: str, prediction: str) -> float:
    """Character Error Rate: edit_distance(ref_chars, pred_chars) / len(ref_chars)."""
    ref_clean = normalize_evaluation_text(reference)
    pred_clean = normalize_evaluation_text(prediction)

    ref_chars = list(ref_clean)
    pred_chars = list(pred_clean)

    if not ref_chars:
        return 0.0 if not pred_chars else 1.0

    dist = levenshtein_distance(ref_chars, pred_chars)
    return round(dist / len(ref_chars), 4)

def compute_wer(reference: str, prediction: str) -> float:
    """Word Error Rate: edit_distance(ref_words, pred_words) / len(ref_words)."""
    ref_clean = normalize_evaluation_text(reference)
    pred_clean = normalize_evaluation_text(prediction)

    ref_words = ref_clean.split()
    pred_words = pred_clean.split()

    if not ref_words:
        return 0.0 if not pred_words else 1.0

    dist = levenshtein_distance(ref_words, pred_words)
    return round(dist / len(ref_words), 4)

def compute_diacritic_accuracy(reference: str, prediction: str) -> float:
    """
    Evaluates Vietnamese diacritic character accuracy.
    Measures ratio of correctly preserved Vietnamese accented letters.
    """
    ref_clean = normalize_evaluation_text(reference)
    pred_clean = normalize_evaluation_text(prediction)

    ref_diacritics = [c for c in ref_clean if c in VIETNAMESE_DIACRITIC_CHARS]
    if not ref_diacritics:
        return 1.0

    pred_diacritics = [c for c in pred_clean if c in VIETNAMESE_DIACRITIC_CHARS]
    dist = levenshtein_distance(ref_diacritics, pred_diacritics)
    correct = max(0, len(ref_diacritics) - dist)
    return round(correct / len(ref_diacritics), 4)

def compute_table_accuracy(reference: str, prediction: str) -> Optional[float]:
    """
    Evaluates table presence and content preservation if reference contains pipe table.
    """
    ref_table_lines = [l for l in reference.splitlines() if "|" in l]
    if not ref_table_lines:
        return None

    pred_table_lines = [l for l in prediction.splitlines() if "|" in l]
    if not pred_table_lines:
        return 0.0

    # Match cell contents
    ref_cells = [c.strip() for l in ref_table_lines for c in l.split("|") if c.strip() and not re.match(r"^:?-+:?$", c.strip())]
    pred_cells = [c.strip() for l in pred_table_lines for c in l.split("|") if c.strip() and not re.match(r"^:?-+:?$", c.strip())]

    if not ref_cells:
        return 1.0

    matched = 0
    for rc in ref_cells:
        if any(rc in pc or pc in rc for pc in pred_cells):
            matched += 1

    return round(matched / len(ref_cells), 4)

def compute_reading_order_accuracy(reference: str, prediction: str) -> float:
    """
    Evaluates reading order alignment of major sentences/paragraphs.
    """
    ref_lines = [l.strip() for l in normalize_evaluation_text(reference).splitlines() if len(l.strip()) > 15]
    pred_clean = normalize_evaluation_text(prediction)

    if len(ref_lines) <= 1:
        return 1.0

    last_pos = -1
    in_order_count = 0

    for l in ref_lines:
        # Find position of key prefix
        prefix = l[:min(25, len(l))]
        pos = pred_clean.find(prefix)
        if pos != -1:
            if pos >= last_pos:
                in_order_count += 1
            last_pos = pos

    return round(in_order_count / len(ref_lines), 4)

def evaluate_page(ref_text: str, pred_text: str, page_num: int) -> PageAccuracyReport:
    """Evaluates a single page against ground truth text."""
    cer = compute_cer(ref_text, pred_text)
    wer = compute_wer(ref_text, pred_text)
    diac_acc = compute_diacritic_accuracy(ref_text, pred_text)
    table_acc = compute_table_accuracy(ref_text, pred_text)
    order_acc = compute_reading_order_accuracy(ref_text, pred_text)

    ref_clean = normalize_evaluation_text(ref_text)
    pred_clean = normalize_evaluation_text(pred_text)

    return PageAccuracyReport(
        page=page_num,
        cer=cer,
        wer=wer,
        diacritic_accuracy=diac_acc,
        table_accuracy=table_acc,
        reading_order_accuracy=order_acc,
        ref_char_count=len(ref_clean),
        pred_char_count=len(pred_clean),
        ref_word_count=len(ref_clean.split()),
        pred_word_count=len(pred_clean.split())
    )

_GT_NAME = re.compile(r"^(?:(?P<prefix>.+?)_)?page_(?P<num>\d+)$", re.IGNORECASE)


def ground_truth_pages(gt_dir: Path, doc_id: str) -> Dict[int, Path]:
    """Ground-truth files that belong to this document.

    `<prefix>_page_NNNN.txt` applies only to documents whose id starts with
    the prefix (clw_page_0001.txt -> CLW_Baocaothuongnien_2020); an
    unprefixed `page_NNNN.txt` applies to any document.
    """
    pages: Dict[int, Path] = {}
    specificity: Dict[int, int] = {}
    for gt_file in sorted(gt_dir.glob("*.txt")):
        match = _GT_NAME.match(gt_file.stem)
        if not match:
            continue
        prefix = match.group("prefix")
        if prefix and not (doc_id.casefold() == prefix.casefold() or
                           doc_id.casefold().startswith(prefix.casefold() + "_")):
            continue
        page_num = int(match.group("num"))
        rank = len(prefix) if prefix else 0
        if page_num in pages and rank == specificity[page_num]:
            raise ValueError(f"Ambiguous ground truth for {doc_id} page {page_num}: "
                             f"{pages[page_num].name}, {gt_file.name}")
        if page_num not in pages or rank > specificity[page_num]:
            pages[page_num] = gt_file
            specificity[page_num] = rank
    return pages


def _selected_pages(prediction_dir: Path) -> Optional[set]:
    """Pages the run was asked to process, from manifest.json if present."""
    try:
        manifest = json.loads((prediction_dir / "manifest.json").read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None
    selected = manifest.get("selected_pages")
    if selected is None:
        return None
    if not isinstance(selected, list) or any(type(page) is not int or page < 1 for page in selected):
        raise ValueError("manifest.selected_pages must be a list of positive page numbers")
    return set(selected)


def evaluate_document(prediction_dir: Path, gt_dir: Path) -> AccuracyReport:
    """Evaluates a document output against its ground-truth pages (proposal 9.1).

    A ground-truth page inside the selected pages whose output is missing is
    MISSING_OUTPUT and scored as maximum error, never skipped. Ground-truth
    pages outside the selected pages are NOT_EVALUATED and listed separately.
    """
    doc_id = prediction_dir.name
    pages_dir = prediction_dir / "pages"
    selected = _selected_pages(prediction_dir)
    page_reports: Dict[int, PageAccuracyReport] = {}
    not_evaluated: List[int] = []
    char_errors = word_errors = 0

    for page_num, gt_file in ground_truth_pages(gt_dir, doc_id).items():
        if selected is not None and page_num not in selected:
            not_evaluated.append(page_num)
            continue
        ref_text = gt_file.read_text(encoding="utf-8")
        candidates = (pages_dir / f"page-{page_num:04d}.md", pages_dir / f"page-{page_num}.md")
        pred_md_file = next((path for path in candidates if path.is_file()), None)
        pred_text = pred_md_file.read_text(encoding="utf-8") if pred_md_file else ""
        ref_clean, pred_clean = normalize_evaluation_text(ref_text), normalize_evaluation_text(pred_text)
        char_errors += levenshtein_distance(list(ref_clean), list(pred_clean))
        word_errors += levenshtein_distance(ref_clean.split(), pred_clean.split())
        if pred_md_file is not None:
            page_reports[page_num] = evaluate_page(ref_text, pred_text, page_num)
        else:
            # Every reference character counts as deleted.
            report = evaluate_page(ref_text, "", page_num)
            report.status = "MISSING_OUTPUT"
            report.reading_order_accuracy = 0.0
            page_reports[page_num] = report

    if not page_reports:
        return AccuracyReport(document_id=doc_id, pages_not_evaluated=not_evaluated)

    ref_chars = sum(r.ref_char_count for r in page_reports.values())
    ref_words = sum(r.ref_word_count for r in page_reports.values())
    # Aggregate integer edit counts, rather than multiplying rounded page rates.
    micro_cer = char_errors / ref_chars if ref_chars else None
    micro_wer = word_errors / ref_words if ref_words else None
    mean_cer = sum(r.cer for r in page_reports.values()) / len(page_reports)
    mean_wer = sum(r.wer for r in page_reports.values()) / len(page_reports)
    mean_diac = sum(r.diacritic_accuracy for r in page_reports.values()) / len(page_reports)
    mean_order = sum(r.reading_order_accuracy for r in page_reports.values()) / len(page_reports)

    table_scores = [r.table_accuracy for r in page_reports.values() if r.table_accuracy is not None]
    mean_table = (sum(table_scores) / len(table_scores)) if table_scores else None

    return AccuracyReport(
        document_id=doc_id,
        mean_cer=round(mean_cer, 4),
        mean_wer=round(mean_wer, 4),
        mean_diacritic_accuracy=round(mean_diac, 4),
        mean_table_accuracy=round(mean_table, 4) if mean_table is not None else None,
        mean_reading_order_accuracy=round(mean_order, 4),
        pages_evaluated=len(page_reports),
        evaluation_status="MEASURED",
        pages_missing_output=sum(1 for r in page_reports.values() if r.status == "MISSING_OUTPUT"),
        pages_not_evaluated=not_evaluated,
        micro_cer=round(micro_cer, 4) if micro_cer is not None else None,
        micro_wer=round(micro_wer, 4) if micro_wer is not None else None,
        page_reports=page_reports
    )

def main():
    parser = argparse.ArgumentParser(description="Codex v3.0 Accuracy Evaluation against Ground Truth")
    parser.add_argument("--prediction", type=str, required=True, help="Path to result.json or doc output folder")
    parser.add_argument("--ground-truth", type=str, default="benchmark/ground_truth", help="Path to ground truth directory")
    parser.add_argument("--output-json", type=str, default=None, help="Save accuracy.json path")

    args = parser.parse_args()

    pred_path = Path(args.prediction).resolve()
    if pred_path.is_file():
        pred_dir = pred_path.parent
    else:
        pred_dir = pred_path

    gt_dir = Path(args.ground_truth).resolve()
    if not gt_dir.exists():
        print(f"[ERROR] Ground truth directory not found: {gt_dir}", file=sys.stderr)
        sys.exit(1)

    report = evaluate_document(pred_dir, gt_dir)

    print("=" * 70)
    print(f"CODEX OCR v3.0 ACCURACY EVALUATION REPORT: {report.document_id}")
    print(f"Pages Evaluated: {report.pages_evaluated}")
    print("=" * 70)

    rows = []
    for p_num, p_rep in sorted(report.page_reports.items()):
        tab_str = f"{p_rep.table_accuracy:.2%}" if p_rep.table_accuracy is not None else "N/A"
        rows.append([
            f"Page {p_num}",
            f"{p_rep.cer:.2%}",
            f"{p_rep.wer:.2%}",
            f"{p_rep.diacritic_accuracy:.2%}",
            tab_str,
            f"{p_rep.reading_order_accuracy:.2%}",
            p_rep.ref_char_count,
            p_rep.pred_char_count
        ])

    headers = ["Page", "CER", "WER", "Diacritic Acc", "Table Acc", "Order Acc", "Ref Chars", "Pred Chars"]
    print(tabulate(rows, headers=headers, tablefmt="github"))

    print("-" * 70)
    summary_data = [
        ["Mean CER", f"{report.mean_cer:.2%}"],
        ["Mean WER", f"{report.mean_wer:.2%}"],
        ["Mean Diacritic Accuracy", f"{report.mean_diacritic_accuracy:.2%}"],
        ["Mean Table Accuracy", f"{report.mean_table_accuracy:.2%}" if report.mean_table_accuracy is not None else "N/A"],
        ["Mean Reading Order Accuracy", f"{report.mean_reading_order_accuracy:.2%}"]
    ]
    print(tabulate(summary_data, headers=["Metric", "Overall Score"], tablefmt="github"))
    print("=" * 70)

    out_json = args.output_json
    if not out_json:
        out_json = pred_dir / "accuracy.json"
    else:
        out_json = Path(out_json)

    with open(out_json, "w", encoding="utf-8") as f:
        json.dump(report.model_dump(mode="json"), f, ensure_ascii=False, indent=2)
    print(f"Accuracy report saved to: {out_json}")

if __name__ == "__main__":
    main()
