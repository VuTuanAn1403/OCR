"""Identify a short, centered pull quote between two continuing prose columns."""
from statistics import median


METHOD = "centered-pull-quote-v1"
QUOTE_ROLES = {"pull_quote", "callout"}
_BODY_ROLES = {"paragraph", "text"}
_CLOSER = {"“": "”", "«": "»", '"': '"'}


def _height(item):
    return item.bbox[3] - item.bbox[1]


def _center(item):
    return (item.bbox[0] + item.bbox[2]) / 2


def _neighbor(a, b):
    h = min(_height(a), _height(b))
    return (max(_height(a), _height(b)) <= 1.4 * h
            and -.15 * h <= b.bbox[1] - a.bbox[3] <= .9 * h
            and min(abs(a.bbox[0] - b.bbox[0]), abs(_center(a) - _center(b))) <= .65 * h
            and min(a.bbox[2], b.bbox[2]) > max(a.bbox[0], b.bbox[0]))


def _candidates(items):
    for first in items:
        text = first.text.strip()
        if not text:
            continue
        explicit = first.role in QUOTE_ROLES
        closer = _CLOSER.get(text[0])
        if not explicit and (closer is None or len(text) < 2 or text[1] in _CLOSER):
            continue
        group = [first]
        payload = text[1:] if closer is not None else text
        while len(group) <= 5:
            tail = payload.rstrip(".!? ")
            closed = closer is not None and tail.endswith(closer) and closer not in tail[:-1]
            if closed or (explicit and closer is None):
                if len(payload.split()) >= 4:
                    yield group, explicit
                if not explicit or closed:
                    break
            if (closer is not None and closer in payload) or len(group) == 5:
                break
            last = group[-1]
            following = [b for b in items if b.bbox[1] > last.bbox[1] and _neighbor(last, b)
                         and (not explicit or b.role in QUOTE_ROLES)]
            if len(following) != 1 or not following[0].text.strip():
                break
            group.append(following[0])
            payload += " " + following[0].text.strip()


def _supports_columns(items, quote, explicit, min_gap):
    ids = {b.id for b in quote}
    body = [b for b in items if b.id not in ids]
    if any(b.role not in _BODY_ROLES for b in body):
        return None
    box = [min(b.bbox[0] for b in quote), min(b.bbox[1] for b in quote),
           max(b.bbox[2] for b in quote), max(b.bbox[3] for b in quote)]
    cut = (box[0] + box[2]) / 2
    left = [b for b in body if b.bbox[2] <= cut]
    right = [b for b in body if b.bbox[0] >= cut]
    if min(len(left), len(right)) < 3 or len(left) + len(right) != len(body):
        return None
    h = median(_height(b) for b in body)
    right_edge, left_edge = max(b.bbox[2] for b in left), min(b.bbox[0] for b in right)
    if left_edge - right_edge < max(min_gap, .35 * h) or not box[0] < (left_edge + right_edge) / 2 < box[2]:
        return None
    body_width = max(b.bbox[2] for b in right) - min(b.bbox[0] for b in left)
    if box[2] - box[0] > .8 * body_width or (not explicit and median(map(_height, quote)) < 1.18 * h):
        return None
    for column in (left, right):
        width = median(b.bbox[2] - b.bbox[0] for b in column)
        if (width < 5 * h or sum(len(b.text.split()) >= 3 for b in column) < .6 * len(column)
                or max(b.bbox[0] for b in column) - min(b.bbox[0] for b in column) > .3 * width
                or not any(b.bbox[3] <= box[1] for b in column) or not any(b.bbox[1] >= box[3] for b in column)):
            return None
    if any(min(b.bbox[2], box[2]) > max(b.bbox[0], box[0])
           and min(b.bbox[3], box[3]) > max(b.bbox[1], box[1]) for b in body):
        return None
    return (left, right), box


def identify_pull_quote(group, *, min_gap):
    """Return a single supported quote and body columns, or abstain."""
    if len(group) < 7 or any(b.kind != "b" for b in group):
        return None
    candidates = []
    for quote, explicit in _candidates(group):
        supported = _supports_columns(group, quote, explicit, min_gap)
        if supported is not None:
            columns, box = supported
            candidates.append((quote, columns, box))
            if len(candidates) > 1:
                return None
    return candidates[0] if candidates else None
