"""Rule-based reading-order challenger for spec 11 (V8-071): R-RO-01..08 on one logical page.

Standard library only and deterministic. Input is the item list of one extraction page
(``id``, ``kind``, ``bbox`` in PDF points top-left, ``role_final``, ``text_corrected``);
output is an order that contains every item exactly once, plus separate streams.

* R-RO-05/06: ``running_header`` items open the page, ``running_footer`` items and then
  ``page_number`` items close it; ``pull_quote`` items follow the main body.
* R-RO-03/04: in the main body, column gutters are x-gaps between items narrower than
  ``NARROW_SHARE`` of the region. An item that crosses a gutter spans columns: the
  columns above it are read, then the item, then the columns below it. Columns read
  left to right, and a column is cut again recursively (nested layouts).
* R-RO-01/02: without a gutter, items form rows by vertical overlap, rows top to bottom
  and items left to right.
* R-RO-07: a caption moves next to the closest table or picture it overlaps
  horizontally: before it when the caption is above, after it when below.
* R-RO-08: body text (text, paragraph, list) that ends a page without a sentence end,
  followed by body text starting in lower case on the next page, is reported as a
  continuation edge (diagnostic; the order is unchanged).

This is a challenger: it never runs in production and its quality is NOT_EVALUATED
until reading-order GT exists.
"""
from __future__ import annotations

from typing import Dict, Iterable, List, Optional, Sequence, Tuple

METHOD = "reading-order-rules-v1"
HEADER_ROLES = ("running_header",)
FOOTER_ROLES = ("running_footer",)
PAGE_NUMBER_ROLES = ("page_number",)
PULL_QUOTE_ROLES = ("pull_quote",)
CAPTION_ROLES = ("caption",)
NARROW_SHARE = 0.55
MIN_GUTTER_POINTS = 6.0
MIN_GUTTER_SHARE = 0.015
ROW_OVERLAP = 0.5
MAX_DEPTH = 3
CAPTION_GAP_HEIGHTS = 3.0
CAPTION_MIN_OVERLAP = 0.3
BACKGROUND_SHARE = 0.6
CONTAINED_SHARE = 0.8
SENTENCE_END = (".", "!", "?", ":", ";", "…", "\"", "”", ")")
BODY_ROLES = ("text", "paragraph", "list")

Box = Tuple[float, float, float, float]


def _box(item: Dict) -> Optional[Box]:
    value = item.get("bbox")
    if isinstance(value, (list, tuple)) and len(value) == 4 and value[2] > value[0] and value[3] > value[1]:
        return tuple(float(v) for v in value)
    return None


def _center_y(box: Box) -> float:
    return (box[1] + box[3]) / 2


def _vertical_overlap(a: Box, b: Box) -> float:
    overlap = min(a[3], b[3]) - max(a[1], b[1])
    smaller = min(a[3] - a[1], b[3] - b[1])
    return overlap / smaller if smaller > 0 else 0.0


def _key(item: Dict) -> Tuple:
    box = item["_box"]
    return (box[1], box[0], box[3], box[2], str(item["id"]))


def rows_order(items: Sequence[Dict]) -> List[Dict]:
    """R-RO-01/02: rows by vertical overlap, top to bottom; left to right inside a row."""
    rows: List[List[Dict]] = []
    for item in sorted(items, key=lambda i: (_center_y(i["_box"]), i["_box"][0], str(i["id"]))):
        # compare with the row's anchor only, so a tall item cannot chain rows together
        for row in rows:
            if _vertical_overlap(row[0]["_box"], item["_box"]) >= ROW_OVERLAP:
                row.append(item)
                break
        else:
            rows.append([item])
    rows.sort(key=lambda row: (min(m["_box"][1] for m in row), min(m["_box"][0] for m in row)))
    return [item for row in rows for item in sorted(row, key=lambda i: (i["_box"][0], _key(i)))]


def gutters(items: Sequence[Dict]) -> List[Tuple[float, float]]:
    """x-gaps between the narrow items of a region, wide enough to separate columns."""
    if len(items) < 2:
        return []
    left = min(i["_box"][0] for i in items)
    right = max(i["_box"][2] for i in items)
    width = right - left
    if width <= 0:
        return []
    narrow = sorted((i["_box"][0], i["_box"][2]) for i in items if i["_box"][2] - i["_box"][0] <= NARROW_SHARE * width)
    if len(narrow) < 2:
        return []
    merged: List[List[float]] = []
    for start, end in narrow:
        if merged and start <= merged[-1][1]:
            merged[-1][1] = max(merged[-1][1], end)
        else:
            merged.append([start, end])
    minimum = max(MIN_GUTTER_POINTS, MIN_GUTTER_SHARE * width)
    return [(a[1], b[0]) for a, b in zip(merged, merged[1:]) if b[0] - a[1] >= minimum]


def _crosses(box: Box, gaps: Sequence[Tuple[float, float]]) -> bool:
    return any(box[0] < end and box[2] > start for start, end in gaps)


def region_order(items: Sequence[Dict], depth: int = 0) -> Tuple[List[Dict], Dict]:
    """Main-body order of one region (R-RO-03/04), with what was detected."""
    gaps = gutters(items) if depth < MAX_DEPTH else []
    if not gaps:
        return rows_order(items), {"columns": 1, "spanning": []}
    spans = sorted((i for i in items if _crosses(i["_box"], gaps)), key=_key)
    rest = [i for i in items if not _crosses(i["_box"], gaps)]
    bands: List[List[Dict]] = [[] for _ in range(len(spans) + 1)]
    for item in rest:
        above = sum(_center_y(span["_box"]) < _center_y(item["_box"]) for span in spans)
        bands[above].append(item)
    ordered: List[Dict] = []
    info = {"columns": len(gaps) + 1, "spanning": [str(s["id"]) for s in spans]}
    for index, band in enumerate(bands):
        columns: List[List[Dict]] = [[] for _ in range(len(gaps) + 1)]
        for item in band:
            center = (item["_box"][0] + item["_box"][2]) / 2
            column = sum(center > (gap[0] + gap[1]) / 2 for gap in gaps)
            columns[column].append(item)
        for column in columns:
            if column:
                nested, _ = region_order(column, depth + 1)
                ordered.extend(nested)
        if index < len(spans):
            ordered.append(spans[index])
    return ordered, info


def attach_captions(sequence: List[Dict]) -> Tuple[List[Dict], List[Dict]]:
    """R-RO-07: move each caption next to the closest table or picture it belongs to."""
    targets = [i for i in sequence if i.get("kind") in ("t", "i") or i.get("role_final") in ("table", "picture")]
    moves = []
    result = list(sequence)
    for caption in [i for i in sequence if i.get("role_final") in CAPTION_ROLES]:
        box, best = caption["_box"], None
        height = box[3] - box[1]
        for target in targets:
            t = target["_box"]
            overlap = min(box[2], t[2]) - max(box[0], t[0])
            narrower = min(box[2] - box[0], t[2] - t[0])
            if narrower <= 0 or overlap / narrower < CAPTION_MIN_OVERLAP:
                continue
            gap = t[1] - box[3] if box[3] <= t[1] + height / 2 else box[1] - t[3]
            if -height / 2 <= gap <= CAPTION_GAP_HEIGHTS * max(height, 1.0):
                if best is None or (gap, str(target["id"])) < best[0]:
                    best = ((gap, str(target["id"])), target, box[3] <= t[1] + height / 2)
        if best is None:
            continue
        _, target, above = best
        result.remove(caption)
        position = result.index(target)
        result.insert(position if above else position + 1, caption)
        moves.append({"caption": str(caption["id"]), "target": str(target["id"]), "placed": "before" if above else "after"})
    return result, moves


def _text(item: Dict) -> str:
    return (item.get("text_corrected") or item.get("text_raw") or "").strip()


def _area(box: Box) -> float:
    return (box[2] - box[0]) * (box[3] - box[1])


def _inside_share(inner: Box, outer: Box) -> float:
    width = min(inner[2], outer[2]) - max(inner[0], outer[0])
    height = min(inner[3], outer[3]) - max(inner[1], outer[1])
    return max(0.0, width) * max(0.0, height) / _area(inner) if _area(inner) > 0 else 0.0


def split_containers(body: Sequence[Dict], page_size: Optional[Sequence[float]] = None):
    """Backgrounds, top-level blocks and the items each table or picture contains.

    A picture or table covering at least ``BACKGROUND_SHARE`` of the page is a background:
    it is read first and takes no part in the layout, otherwise every line would overlap
    it. Any other item that lies at least ``CONTAINED_SHARE`` inside a table or picture
    belongs to the smallest such container and is read right after it (R-RO-07).
    """
    if page_size and page_size[0] and page_size[1]:
        page_area = float(page_size[0]) * float(page_size[1])
    else:
        boxes = [i["_box"] for i in body]
        page_area = _area((min(b[0] for b in boxes), min(b[1] for b in boxes), max(b[2] for b in boxes),
                           max(b[3] for b in boxes))) if boxes else 0.0
    is_container = lambda i: i.get("kind") in ("t", "i") or i.get("role_final") in ("table", "picture")  # noqa: E731
    backgrounds = [i for i in body if is_container(i) and page_area and _area(i["_box"]) >= BACKGROUND_SHARE * page_area]
    background_ids = set(map(id, backgrounds))
    containers = sorted((i for i in body if is_container(i) and id(i) not in background_ids), key=lambda i: (_area(i["_box"]), str(i["id"])))
    children: Dict[int, List[Dict]] = {}
    blocks = []
    for item in body:
        if id(item) in background_ids:
            continue
        owner = next((c for c in containers if c is not item and _area(c["_box"]) > _area(item["_box"])
                      and _inside_share(item["_box"], c["_box"]) >= CONTAINED_SHARE), None)
        if owner is None:
            blocks.append(item)
        else:
            children.setdefault(id(owner), []).append(item)
    return backgrounds, blocks, children


def expand(block: Dict, children: Dict[int, List[Dict]]) -> List[Dict]:
    """A block followed by its contents in row order; nested containers bring their own contents."""
    result = [block]
    for child in rows_order(children.get(id(block), [])):
        result.extend(expand(child, children))
    return result


def order_page(items: Iterable[Dict], page_size: Optional[Sequence[float]] = None) -> Dict:
    """Challenger order for one page; every input item appears exactly once."""
    prepared = []
    for item in items:
        prepared.append({**item, "_box": _box(item)})
    ids = [str(i["id"]) for i in prepared]
    if len(set(ids)) != len(ids):
        raise ValueError("item ids repeat on the page")
    unplaced = [i for i in prepared if i["_box"] is None]
    placed = [i for i in prepared if i["_box"] is not None]
    role = lambda i: i.get("role_final")  # noqa: E731
    header = sorted((i for i in placed if role(i) in HEADER_ROLES), key=lambda i: (i["_box"][1], i["_box"][0], str(i["id"])))
    footer = sorted((i for i in placed if role(i) in FOOTER_ROLES), key=lambda i: (i["_box"][1], i["_box"][0], str(i["id"])))
    numbers = sorted((i for i in placed if role(i) in PAGE_NUMBER_ROLES), key=lambda i: (i["_box"][1], i["_box"][0], str(i["id"])))
    quotes = sorted((i for i in placed if role(i) in PULL_QUOTE_ROLES), key=_key)
    special = set(map(id, header + footer + numbers + quotes))
    body = [i for i in placed if id(i) not in special]
    backgrounds, blocks, children = split_containers(body, page_size)
    laid_out, info = region_order(blocks)
    laid_out, captions = attach_captions(laid_out)  # on blocks, so a caption never splits a table from its cells
    main = sorted(backgrounds, key=_key)
    for block in laid_out:
        main.extend(expand(block, children))
    main.extend(sorted(unplaced, key=lambda i: str(i["id"])))
    order = [str(i["id"]) for i in header + main + quotes + footer + numbers]
    if sorted(order) != sorted(ids):
        raise AssertionError("reading order lost or duplicated an item")
    return {"method": METHOD, "order": order,
            "streams": {"header": [str(i["id"]) for i in header], "main": [str(i["id"]) for i in main],
                        "pull_quote": [str(i["id"]) for i in quotes], "footer": [str(i["id"]) for i in footer + numbers]},
            "columns": info["columns"], "spanning_items": info["spanning"], "caption_moves": captions,
            "items_without_bbox": [str(i["id"]) for i in unplaced],
            "_main_items": main}


def continuation_edges(pages: Sequence[Dict]) -> List[Dict]:
    """R-RO-08: body text that ends a page without a sentence end continues on the next page."""
    edges = []
    for current, following in zip(pages, pages[1:]):
        last = next((i for i in reversed(current["_main_items"]) if _text(i) and i.get("role_final") in BODY_ROLES), None)
        first = next((i for i in following["_main_items"] if _text(i) and i.get("role_final") in BODY_ROLES), None)
        if (last is not None and first is not None and not _text(last).endswith(SENTENCE_END)
                and _text(first)[:1].islower()):
            edges.append({"from": str(last["id"]), "to": str(first["id"]), "kind": "page"})
    return edges


def pair_agreement(reference: Sequence[str], candidate: Sequence[str]) -> Dict:
    """Share of item pairs ordered the same way in two orders over the same items."""
    common = [item for item in reference if item in set(candidate)]
    position = {item: index for index, item in enumerate(candidate)}
    n = len(common)
    if n < 2:
        return {"items": n, "pairs": 0, "agreeing_pairs": 0, "agreement": None}
    # count inversions of candidate positions taken in reference order (merge sort)
    values = [position[item] for item in common]

    def count(seq):
        if len(seq) < 2:
            return seq, 0
        middle = len(seq) // 2
        left, a = count(seq[:middle])
        right, b = count(seq[middle:])
        merged, inversions, i, j = [], a + b, 0, 0
        while i < len(left) and j < len(right):
            if left[i] <= right[j]:
                merged.append(left[i])
                i += 1
            else:
                merged.append(right[j])
                inversions += len(left) - i
                j += 1
        merged.extend(left[i:])
        merged.extend(right[j:])
        return merged, inversions

    _, inversions = count(values)
    pairs = n * (n - 1) // 2
    return {"items": n, "pairs": pairs, "agreeing_pairs": pairs - inversions, "agreement": (pairs - inversions) / pairs}


def rule_violations(order: Sequence[str], items: Sequence[Dict]) -> Dict:
    """R-RO-05 and R-RO-07 checks of any order (product or challenger), without GT."""
    by_id = {str(i["id"]): i for i in items}
    roles = [by_id[item].get("role_final") for item in order if item in by_id]
    body = [index for index, value in enumerate(roles) if value not in HEADER_ROLES + FOOTER_ROLES + PAGE_NUMBER_ROLES]
    header_after_body = sum(1 for index, value in enumerate(roles) if value in HEADER_ROLES and body and index > body[0])
    footer_before_body = sum(1 for index, value in enumerate(roles)
                             if value in FOOTER_ROLES + PAGE_NUMBER_ROLES and body and index < body[-1])
    return {"header_after_body": header_after_body, "footer_before_body": footer_before_body}
