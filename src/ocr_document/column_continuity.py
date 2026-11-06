"""Conservative, reviewable prose continuation across aligned column ends."""
from dataclasses import replace
from statistics import median

from ocr_document.source_identity import valid_bbox

METHOD = "aligned-column-continuation-v1"
_PROSE = {"text", "paragraph", "list", "list_item"}


def _column_key(line):
    return line.page, line.article_group_id, line.column_id


def _columns(flow):
    groups = {}
    for kind, paragraph in flow:
        if kind != "paragraph":
            continue
        for line in paragraph.lines:
            if (line.column_id and line.article_group_id and line.block_type in _PROSE
                    and valid_bbox(line.bbox)):
                groups.setdefault(_column_key(line), []).append(line)
    columns = {}
    for key, lines in groups.items():
        if len(lines) < 4:
            continue
        columns[key] = {
            "left": median(line.bbox[0] for line in lines),
            "right": median(line.bbox[2] for line in lines),
            "top": min(line.bbox[1] for line in lines),
            "bottom": max(line.bbox[3] for line in lines),
            "height": median(line.height for line in lines),
        }
    return columns


def _evidence(previous, following, images, columns, barriers):
    a, b = previous.lines[-1], following.lines[0]
    ka, kb = _column_key(a), _column_key(b)
    if (a.page != b.page or not a.article_group_id or a.article_group_id != b.article_group_id
            or not a.column_id or not b.column_id or a.column_id == b.column_id
            or a.block_type not in _PROSE or b.block_type not in _PROSE
            or not valid_bbox(a.bbox) or not valid_bbox(b.bbox) or ka not in columns or kb not in columns):
        return None
    # Uppercase, list markers, numbered items and completed sentences start
    # new paragraphs even when the boxes happen to line up.
    left_text, right_text = a.text.rstrip(), b.text.lstrip()
    if (not left_text or not right_text or not right_text[0].islower()
            or not (left_text[-1].isalpha() or left_text[-1] in ",-–")
            or following.kind != "paragraph" or bool(a.is_bold) != bool(b.is_bold)
            or (a.font_size and b.font_size and abs(a.font_size - b.font_size) > 1.5)):
        return None
    ca, cb = columns[ka], columns[kb]
    h = max(ca["height"], cb["height"])
    wa, wb = ca["right"] - ca["left"], cb["right"] - cb["left"]
    siblings = sorted((key for key in columns if key[:2] == ka[:2]), key=lambda key: (columns[key]["left"], key[2]))
    if siblings.index(kb) != siblings.index(ka) + 1:
        return None
    if (min(wa, wb) < 6 * h or min(wa, wb) < .8 * max(wa, wb)
            or ca["right"] >= cb["left"] or cb["left"] - ca["right"] > 2 * max(wa, wb)
            or min(ca["height"], cb["height"]) < .75 * h
            or abs(ca["top"] - cb["top"]) > 2 * h
            or abs(ca["bottom"] - cb["bottom"]) > 2 * h
            or abs(a.bbox[3] - ca["bottom"]) > .25 * h
            or abs(b.bbox[1] - cb["top"]) > .25 * h
            or a.bbox[2] < ca["right"] - .75 * h
            or abs(b.bbox[0] - cb["left"]) > .5 * h
            or b.bbox[1] + 3 * h >= a.bbox[1]
            or min(a.height, b.height) < .65 * h or max(a.height, b.height) > 1.5 * h):
        return None
    # A later table can contain the missing tail of the left column. Likewise,
    # a heading inside either column separates articles/sections even when the
    # recursive layout reused the same column id above and below that heading.
    for page, box in barriers:
        if page != a.page:
            continue
        if not valid_bbox(box):
            return None
        if any(box[0] < col["right"] and box[2] > col["left"]
               and box[1] < col["bottom"] + 2 * h and box[3] > col["top"] for col in (ca, cb)):
            return None
    # Only top illustrations may move ahead of the complete paragraph. A
    # table, formula, caption, inline image or unknown geometry is a barrier.
    for _, item in images:
        if (item.page != a.page or not valid_bbox(item.bbox)
                or item.region.content_type.value not in {"IMAGE", "FIGURE"}
                or item.bbox[3] > min(ca["top"], cb["top"])):
            return None
    return {"method": METHOD, "status": "NEEDS_REVIEW", "page": a.page,
            "before_item_id": a.item_id, "after_item_id": b.item_id,
            "before_source_id": a.source_id, "after_source_id": b.source_id,
            "before_bbox": list(a.bbox), "after_bbox": list(b.bbox),
            "before_column_id": a.column_id, "after_column_id": b.column_id,
            "article_group_id": a.article_group_id,
            "column_geometry": {"before": dict(ca), "after": dict(cb)},
            "moved_image_ids": [item.id for _, item in images]}


def join_column_continuations(flow, join_lines):
    """Join only an adjacent, unfinished paragraph at aligned column edges.

    Source text/boxes and extraction order stay intact. Each inferred join is
    reviewable in the document chunk, including any relocated illustrations.
    """
    columns = _columns(flow)
    barriers = []
    for kind, value in flow:
        if kind == "item":
            barriers.append((value.page, value.bbox))
        else:
            lines = value.heading.lines if kind == "heading" else value.lines
            barriers.extend((line.page, line.bbox) for line in lines
                            if kind == "heading" or (line.block_type not in _PROSE and not line.callout_id))
    result = []
    for kind, value in flow:
        position = len(result) - 1
        if kind == "paragraph":
            while position >= 0 and result[position][0] == "item" and result[position][1].kind == "i":
                position -= 1
            if position >= 0 and result[position][0] == "paragraph":
                previous = result[position][1]
                images = result[position + 1:]
                record = _evidence(previous, value, images, columns, barriers)
                if record:
                    lines = previous.lines + [replace(value.lines[0], structure_needs_review=True)] + value.lines[1:]
                    merged = replace(previous, lines=lines, text=join_lines(lines),
                                     continuations=previous.continuations + [record] + value.continuations)
                    result[position:] = images + [("paragraph", merged)]
                    continue
        result.append((kind, value))
    return result
