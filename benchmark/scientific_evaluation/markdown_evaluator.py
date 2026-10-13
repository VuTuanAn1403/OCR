"""
Direct Final Markdown Evaluator.
Adheres strictly to RESEARCH_PROTOCOL_V5.md Section 3 & Section 4:
- Evaluates the final emitted Markdown file directly (not intermediate JSON).
- Extracts clean body text for CER/WER/DER computation.
- Extracts pipe tables and embedded HTML tables for TEDS evaluation.
- Verifies image links, existence of referenced image files, and rendering integrity.
"""

from typing import Dict, Any, List, Optional, Tuple
from pathlib import Path
import re
import unicodedata
from bs4 import BeautifulSoup
from .ocr_metric import compute_cer, compute_wer, compute_der, compute_cer_detailed, normalize_text_policy
from .teds_metric import compute_teds, compute_teds_struct, evaluate_table_collection


_IMAGE_LINK_PATTERN = re.compile(r"!\[([^\]]*)\]\(([^)]+)\)")
_PIPE_TABLE_PATTERN = re.compile(r"(?:^\|.+\|\s*$\n?)+", re.MULTILINE)
_HTML_TABLE_PATTERN = re.compile(r"<table\b[^>]*>(?:(?!</table>).)*</table>", re.IGNORECASE | re.DOTALL)
_PAGE_MARKER_PATTERN = re.compile(r"(?:<!--\s*(?:page|trang)\s*:?\s*(\d+)\s*-->|(?:\n|^)#+\s*(?:Trang|Page)\s+(\d+))", re.IGNORECASE)


def parse_markdown_artifacts(markdown_path: Path, policy: str = "reading_normalized_v1") -> Dict[str, Any]:
    """
    Parses a Markdown file and extracts its structural components.
    Strictly parses only the given markdown_path without fallback to sibling directories.
    """
    if not markdown_path.is_file():
        raise FileNotFoundError(f"Markdown file does not exist: {markdown_path}")

    raw_text = markdown_path.read_text(encoding="utf-8")
    doc_dir = markdown_path.parent

    # 1. Image links and asset resolution
    image_links: List[Dict[str, Any]] = []
    broken_links: List[str] = []
    for match in _IMAGE_LINK_PATTERN.finditer(raw_text):
        alt_text = match.group(1)
        rel_path = match.group(2)
        # Resolve target path relative to markdown file directory
        target_path = (doc_dir / rel_path).resolve()
        exists = target_path.is_file()
        if not exists:
            broken_links.append(rel_path)
        image_links.append({
            "alt_text": alt_text,
            "target_path": str(target_path),
            "relative_link": rel_path,
            "exists": exists
        })

    # 2. Extract HTML tables
    html_tables: List[str] = _HTML_TABLE_PATTERN.findall(raw_text)

    # 3. Extract pipe tables and convert them to HTML for unified TEDS evaluation
    pipe_tables_raw = _PIPE_TABLE_PATTERN.findall(raw_text)
    converted_pipe_tables: List[str] = []
    for pt in pipe_tables_raw:
        html_conv = _pipe_table_to_html(pt)
        if html_conv:
            converted_pipe_tables.append(html_conv)

    all_tables_html = html_tables + converted_pipe_tables

    # 4. Extract stripped plain text (stripping markdown markup, links, table syntax)
    clean_text = _strip_markdown_for_text_evaluation(raw_text, policy=policy)

    # 5. Extract per-page contents if page markers are present
    pages_text: Dict[int, str] = {}
    markers = list(_PAGE_MARKER_PATTERN.finditer(raw_text))
    if markers:
        for i, m in enumerate(markers):
            page_num = int(m.group(1) or m.group(2))
            start_pos = m.end()
            end_pos = markers[i + 1].start() if i + 1 < len(markers) else len(raw_text)
            page_slice = raw_text[start_pos:end_pos].strip("\r\n")
            pages_text[page_num] = _strip_markdown_for_text_evaluation(page_slice, policy=policy)

    return {
        "raw_text": raw_text,
        "clean_text": clean_text,
        "pages_text": pages_text,
        "tables_html": all_tables_html,
        "image_links": image_links,
        "broken_images": broken_links,
        "has_embedded_html_tables": len(html_tables) > 0,
        "pipe_table_count": len(converted_pipe_tables),
        "total_table_count": len(all_tables_html),
    }


def _pipe_table_to_html(pipe_markdown: str) -> Optional[str]:
    """Converts a Markdown pipe table into standard HTML <table>."""
    lines = [line.strip() for line in pipe_markdown.strip().splitlines() if line.strip()]
    if len(lines) < 2:
        return None

    rows = []
    for line in lines:
        if re.match(r"^\|(?:\s*:?-{3,}:?\s*\|)+\s*$", line):
            continue  # Separator line
        cells = [c.strip() for c in line.strip("|").split("|")]
        rows.append(cells)

    if not rows:
        return None

    html_parts = ["<table>"]
    # First row as header
    html_parts.append("<tr>" + "".join(f"<th>{c}</th>" for c in rows[0]) + "</tr>")
    for row in rows[1:]:
        html_parts.append("<tr>" + "".join(f"<td>{c}</td>" for c in row) + "</tr>")
    html_parts.append("</table>")
    return "".join(html_parts)


def _strip_markdown_for_text_evaluation(md_content: str, policy: str = "reading_normalized_v1") -> str:
    """
    Extracts text content from Markdown, removing markdown markup, links, images, and HTML tags.
    """
    text = md_content
    # Exporter-generated page markers and table separators are not PDF text.
    text = re.sub(r"^#+\s*(?:Trang|Page)\s+\d+[^\r\n]*(?:\r?\n|$)", "", text,
                  flags=re.MULTILINE | re.IGNORECASE)
    text = re.sub(r"^\|\s*[-:\s|]+\|\s*(?:\r?\n|$)", "", text, flags=re.MULTILINE)
    # Remove image links
    text = _IMAGE_LINK_PATTERN.sub(" ", text)
    # Remove standard links [text](url) -> text
    text = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", text)
    # Remove HTML tags
    text = re.sub(r"<[^>]+>", " ", text)
    # Remove Markdown headers (#, ##, etc.)
    text = re.sub(r"^#+\s*", "", text, flags=re.MULTILINE)
    # Remove bold/italic markers
    text = re.sub(r"[*_]{1,3}", "", text)
    # Remove blockquotes
    text = re.sub(r"^>\s*", "", text, flags=re.MULTILINE)
    # Remove table pipe bars
    text = re.sub(r"\|", " ", text)
    # V6 primary scores preserve visible whitespace; the legacy call uses the
    # explicitly labelled secondary policy.
    return normalize_text_policy(text, policy=policy)


def evaluate_final_markdown(
    markdown_path: Path,
    ground_truth_text: Optional[str] = None,
    ground_truth_tables_html: Optional[List[str]] = None,
    partial_gt: bool = False
) -> Dict[str, Any]:
    """
    Directly evaluates a final exported Markdown file against Ground Truth:
    - Verifies image links and asset existence
    - Computes CER, WER, and DER directly on extracted Markdown text
    - Computes TEDS on all extracted Markdown tables
    - partial_gt: If True, evaluates only covered items without penalizing unannotated elements
    """
    parsed = parse_markdown_artifacts(markdown_path)

    results: Dict[str, Any] = {
        "markdown_file": str(markdown_path.resolve()),
        "image_count": len(parsed["image_links"]),
        "broken_image_count": len(parsed["broken_images"]),
        "broken_images": parsed["broken_images"],
        "table_count": parsed["total_table_count"],
        "has_embedded_html_tables": parsed["has_embedded_html_tables"],
        "text_evaluation": None,
        "table_evaluation": None,
    }

    if ground_truth_text is not None:
        cer_detail = compute_cer_detailed(ground_truth_text, parsed["clean_text"])
        wer = compute_wer(ground_truth_text, parsed["clean_text"])
        der = compute_der(ground_truth_text, parsed["clean_text"])
        results["text_evaluation"] = {
            "cer": cer_detail["cer"],
            "wer": wer,
            "der": der,
            "counts": {
                "substitutions": cer_detail["substitutions"],
                "deletions": cer_detail["deletions"],
                "insertions": cer_detail["insertions"],
                "hits": cer_detail["hits"],
                "reference_length": cer_detail["reference_length"],
            },
            "status": cer_detail["status"],
            "gt_char_count": len(ground_truth_text),
            "extracted_char_count": len(parsed["clean_text"]),
        }

    if ground_truth_tables_html is not None:
        gt_tab_objs = [{"html": h, "table_id": f"gt_{i}"} for i, h in enumerate(ground_truth_tables_html)]
        pred_tab_objs = [{"html": h, "table_id": f"pred_{i}"} for i, h in enumerate(parsed["tables_html"])]
        results["table_evaluation"] = evaluate_table_collection(gt_tab_objs, pred_tab_objs)

    return results


def evaluate_multipage_markdown(
    markdown_path: Path,
    ground_truth_by_page: Dict[int, str],
    allow_page_fallback: bool = False
) -> Dict[str, Any]:
    """
    Evaluates multi-page Markdown adherence.
    Acceptance A07: TUYỆT ĐỐI KHÔNG fallback sang pages/page-*.md khi allow_page_fallback=False.
    If a page is missing from result.md, reports ALIGNMENT_FAILED and penalizes missing text.
    """
    if not markdown_path.is_file():
        raise FileNotFoundError(f"Markdown file does not exist: {markdown_path}")

    # Explicit check: Never look at pages/ directory
    parsed = parse_markdown_artifacts(markdown_path)
    pages_text = parsed["pages_text"]

    missing_pages: List[int] = []
    page_results: Dict[int, Any] = {}

    total_gt_len = sum(len(txt) for txt in ground_truth_by_page.values())
    total_deletions = 0
    total_substitutions = 0
    total_insertions = 0
    total_hits = 0

    for page_num, gt_text in ground_truth_by_page.items():
        if page_num not in pages_text or not pages_text[page_num].strip():
            missing_pages.append(page_num)
            page_results[page_num] = {
                "status": "PAGE_MISSING_IN_MARKDOWN",
                "cer": 1.0 if gt_text else 0.0,
                "counts": {
                    "substitutions": 0,
                    "deletions": len(gt_text),
                    "insertions": 0,
                    "hits": 0,
                    "reference_length": len(gt_text),
                }
            }
            total_deletions += len(gt_text)
        else:
            detail = compute_cer_detailed(gt_text, pages_text[page_num])
            page_results[page_num] = detail
            total_substitutions += detail["substitutions"]
            total_deletions += detail["deletions"]
            total_insertions += detail["insertions"]
            total_hits += detail["hits"]

    overall_cer = round(float(total_substitutions + total_deletions + total_insertions) / total_gt_len, 4) if total_gt_len > 0 else None

    return {
        "status": "ALIGNMENT_FAILED" if missing_pages else "OK",
        "missing_pages": missing_pages,
        "overall_cer": overall_cer,
        "total_gt_length": total_gt_len,
        "page_results": page_results,
        "fallback_used": False,
    }
