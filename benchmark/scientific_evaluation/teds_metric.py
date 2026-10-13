"""
Tree Edit Distance-based Similarity (TEDS) Metric for Table Evaluation.
Adheres strictly to the official IBM PubTabNet / ICDAR Table Evaluation Standard.

References:
- Zhong et al., "Image-based table recognition: data, model, and evaluation", ECCV 2020.
- IBM PubTabNet: https://github.com/ibm-aur-nlp/PubTabNet
- RESEARCH_PROTOCOL_V5.md Section 4 & Section 8.
"""

from typing import Optional, List, Dict, Any, Tuple
import re
from bs4 import BeautifulSoup
from apted import APTED, Config
from apted.helpers import Tree
from benchmark.evaluate import levenshtein_distance
from .spatial_matching import match_tables


class TableTree(Tree):
    """
    Table tree representation conforming to IBM PubTabNet reference implementation.
    """
    def __init__(
        self,
        tag: str,
        colspan: int = 1,
        rowspan: int = 1,
        content: Optional[str] = None,
        children: Optional[List["TableTree"]] = None,
    ):
        self.tag = tag.lower()
        self.colspan = int(colspan) if colspan else 1
        self.rowspan = int(rowspan) if rowspan else 1
        self.content = content or ""
        self.children = children if children is not None else []

    def size(self) -> int:
        return 1 + sum(child.size() for child in self.children)

    def bracket(self) -> str:
        """Show tree using brackets notation."""
        if self.tag in ("td", "th"):
            result = f'"tag": {self.tag}, "colspan": {self.colspan}, "rowspan": {self.rowspan}, "text": {self.content}'
        else:
            result = f'"tag": {self.tag}'
        for child in self.children:
            result += child.bracket()
        return f"{{{result}}}"

    def __repr__(self) -> str:
        if self.content:
            return f"<{self.tag} cs={self.colspan} rs={self.rowspan}>{self.content}</{self.tag}>"
        return f"<{self.tag}>"


class PubTabNetConfig(Config):
    """
    APTED configuration matching IBM PubTabNet CustomConfig:
    - Compares tag, colspan, and rowspan.
    - If tag, colspan, or rowspan differ, rename cost is 1.0.
    - If cell tags match, calculates normalized Levenshtein distance on content.
    """
    def __init__(self, structure_only: bool = False):
        self.structure_only = structure_only

    def rename(self, node1: TableTree, node2: TableTree) -> float:
        if (
            (node1.tag != node2.tag)
            or (node1.colspan != node2.colspan)
            or (node1.rowspan != node2.rowspan)
        ):
            return 1.0

        if node1.tag in ("td", "th"):
            if self.structure_only:
                return 0.0
            if node1.content or node2.content:
                max_len = max(len(node1.content), len(node2.content))
                if max_len == 0:
                    return 0.0
                dist = levenshtein_distance(list(node1.content), list(node2.content))
                return float(dist) / max_len
        return 0.0

    def children(self, node: TableTree) -> List[TableTree]:
        return node.children


def _clean_text(text: str) -> str:
    """Normalizes whitespace within cell content."""
    return " ".join(text.split())


def _html_to_tree(html_content: str, structure_only: bool = False) -> Optional[TableTree]:
    """
    Parses HTML table markup into a PubTabNet-compatible TableTree hierarchy.
    """
    if not html_content or not html_content.strip():
        return None

    soup = BeautifulSoup(html_content, "html.parser")
    table = soup.find("table")
    if not table:
        return None

    root = TableTree("table")

    # Find rows inside thead, tbody, or directly inside table
    tr_elements = table.find_all("tr")
    for tr in tr_elements:
        tr_node = TableTree("tr")
        root.children.append(tr_node)
        for cell in tr.find_all(["td", "th"]):
            tag = "td"  # Normalize th to td for PubTabNet standard comparison
            colspan_val = cell.get("colspan", 1)
            rowspan_val = cell.get("rowspan", 1)
            try:
                colspan = int(colspan_val)
            except (ValueError, TypeError):
                colspan = 1
            try:
                rowspan = int(rowspan_val)
            except (ValueError, TypeError):
                rowspan = 1

            cell_text = "" if structure_only else _clean_text(cell.get_text())
            cell_node = TableTree(
                tag=tag,
                colspan=colspan,
                rowspan=rowspan,
                content=cell_text
            )
            tr_node.children.append(cell_node)

    return root


def compute_teds(reference_html: str, prediction_html: str) -> float:
    """
    Computes global Tree Edit Distance-based Similarity (TEDS):
    TEDS = 1 - TreeEditDist(T_ref, T_pred) / max(|T_ref|, |T_pred|)
    Returns float in [0.0, 1.0].
    """
    ref_tree = _html_to_tree(reference_html, structure_only=False)
    pred_tree = _html_to_tree(prediction_html, structure_only=False)

    if ref_tree is None or pred_tree is None:
        return 0.0

    n_ref = max(0, ref_tree.size() - 1)
    n_pred = max(0, pred_tree.size() - 1)
    max_nodes = max(n_ref, n_pred)
    if max_nodes == 0:
        return 1.0

    try:
        apted = APTED(ref_tree, pred_tree, PubTabNetConfig(structure_only=False))
        distance = apted.compute_edit_distance()
        return round(max(0.0, 1.0 - (float(distance) / max_nodes)), 4)
    except Exception:
        return 0.0


def compute_teds_struct(reference_html: str, prediction_html: str) -> float:
    """
    Computes structure-only TEDS (TEDS-struct):
    Evaluates purely the grid rows, columns, and spanning cells, ignoring text contents.
    Returns float in [0.0, 1.0].
    """
    ref_tree = _html_to_tree(reference_html, structure_only=True)
    pred_tree = _html_to_tree(prediction_html, structure_only=True)

    if ref_tree is None or pred_tree is None:
        return 0.0

    n_ref = max(0, ref_tree.size() - 1)
    n_pred = max(0, pred_tree.size() - 1)
    max_nodes = max(n_ref, n_pred)
    if max_nodes == 0:
        return 1.0

    try:
        apted = APTED(ref_tree, pred_tree, PubTabNetConfig(structure_only=True))
        distance = apted.compute_edit_distance()
        return round(max(0.0, 1.0 - (float(distance) / max_nodes)), 4)
    except Exception:
        return 0.0


def evaluate_table_collection(
    gt_tables: List[Dict[str, Any]],
    pred_tables: List[Dict[str, Any]],
    iou_threshold: float = 0.5,
) -> Dict[str, Any]:
    """
    Evaluates a collection of tables for a page or document adhering to Section 4 & Acceptance A10, A15:
    - Separates Table Detection (Precision, Recall, F1) from Table Recognition (TEDS).
    - Matches one-to-one by IoU >= 0.5 in the same document/page.
      Explicit shared table IDs support legacy annotations without boxes.
    - If no GT tables exist: mean_teds is None, status='NO_TABLES' (or 'SPURIOUS_TABLES_ONLY').
    - Reports matched_mean_teds, spurious_table_count, missing_table_count.
    """
    n_gt = len(gt_tables) if gt_tables else 0
    n_pred = len(pred_tables) if pred_tables else 0

    if n_gt == 0 and n_pred == 0:
        return {
            "mean_teds": None,
            "mean_teds_struct": None,
            "matched_mean_teds": None,
            "matched_mean_teds_struct": None,
            "matched_tables": 0,
            "gt_table_count": 0,
            "pred_table_count": 0,
            "missing_table_count": 0,
            "spurious_table_count": 0,
            "hallucinated_table_count": 0,
            "table_precision": 1.0,
            "table_recall": 1.0,
            "table_f1": 1.0,
            "status": "NO_TABLES",
        }

    if n_gt == 0 and n_pred > 0:
        return {
            "mean_teds": None,
            "mean_teds_struct": None,
            "matched_mean_teds": None,
            "matched_mean_teds_struct": None,
            "matched_tables": 0,
            "gt_table_count": 0,
            "pred_table_count": n_pred,
            "missing_table_count": 0,
            "spurious_table_count": n_pred,
            "hallucinated_table_count": n_pred,
            "table_precision": 0.0,
            "table_recall": None,
            "table_f1": 0.0,
            "status": "SPURIOUS_TABLES_ONLY",
        }

    if n_gt > 0 and n_pred == 0:
        return {
            "mean_teds": 0.0,
            "mean_teds_struct": 0.0,
            "matched_mean_teds": None,
            "matched_mean_teds_struct": None,
            "matched_tables": 0,
            "gt_table_count": n_gt,
            "pred_table_count": 0,
            "missing_table_count": n_gt,
            "spurious_table_count": 0,
            "hallucinated_table_count": 0,
            "table_precision": None,
            "table_recall": 0.0,
            "table_f1": 0.0,
            "status": "ALL_TABLES_MISSING",
        }

    pairs = [(gt_tables[row], pred_tables[col])
             for row, col in match_tables(gt_tables, pred_tables, iou_threshold)]

    matched_teds: List[float] = []
    matched_teds_struct: List[float] = []

    for g_tab, p_tab in pairs:
        g_html = g_tab.get("html", "")
        p_html = p_tab.get("html", "")
        matched_teds.append(compute_teds(g_html, p_html))
        matched_teds_struct.append(compute_teds_struct(g_html, p_html))

    matched_count = len(pairs)
    missing_count = n_gt - matched_count
    spurious_count = n_pred - matched_count

    table_precision = round(matched_count / n_pred, 4) if n_pred > 0 else 0.0
    table_recall = round(matched_count / n_gt, 4) if n_gt > 0 else 0.0
    if (table_precision + table_recall) > 0:
        table_f1 = round(2.0 * table_precision * table_recall / (table_precision + table_recall), 4)
    else:
        table_f1 = 0.0

    matched_mean = (sum(matched_teds) / matched_count) if matched_count > 0 else None
    matched_mean_struct = (sum(matched_teds_struct) / matched_count) if matched_count > 0 else None

    # Penalized overall score includes missing tables with 0.0 score
    penalized_scores = list(matched_teds) + [0.0] * missing_count
    mean_teds = sum(penalized_scores) / len(penalized_scores) if penalized_scores else 0.0
    penalized_struct = list(matched_teds_struct) + [0.0] * missing_count
    mean_teds_struct = sum(penalized_struct) / len(penalized_struct) if penalized_struct else 0.0

    return {
        "mean_teds": round(mean_teds, 4),
        "mean_teds_struct": round(mean_teds_struct, 4),
        "matched_mean_teds": round(matched_mean, 4) if matched_mean is not None else None,
        "matched_mean_teds_struct": round(matched_mean_struct, 4) if matched_mean_struct is not None else None,
        "matched_tables": matched_count,
        "gt_table_count": n_gt,
        "pred_table_count": n_pred,
        "missing_table_count": missing_count,
        "spurious_table_count": spurious_count,
        "hallucinated_table_count": spurious_count,
        "table_precision": table_precision,
        "table_recall": table_recall,
        "table_f1": table_f1,
        "status": "OK" if missing_count == 0 and spurious_count == 0 else "PARTIAL",
    }
