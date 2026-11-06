"""Target-phrase effects of real retry records; diagnostic labels cannot grant acceptance."""
from __future__ import annotations

import re
import unicodedata

from ocr_text.numeric_guard import preserves_numeric_evidence


def _literal_count(text, phrase):
    text = unicodedata.normalize("NFC", text).casefold()
    phrase = unicodedata.normalize("NFC", phrase).casefold()
    return len(re.findall(r"(?<!\w)"+re.escape(phrase)+r"(?!\w)", text))


def summarize_retry_effects(cases, labels, results, *, dpi):
    """Count fixes and damage with explicit denominators, never invent missing labels.

    This measures only the specified phrase, not whole-line transcription. The
    original sample is purposive development data. Even a human-reviewed label
    here cannot substitute for the release gate's locked independent GT.
    """
    def index(rows):
        by_id = {row["case_id"]: row for row in rows}
        if len(by_id) != len(rows):
            raise ValueError("Duplicate retry case ID")
        return by_id
    sources, annotations, predictions = map(index, (cases, labels, results))
    if set(sources) != set(annotations) or set(sources) != set(predictions):
        raise ValueError("Retry source/label/result coverage differs")
    counts = {key: 0 for key in ("eligible", "label_unresolved", "before_wrong", "before_correct", "fixed",
                                "still_wrong", "harmed", "preserved_correct", "attempted", "applied",
                                "numeric_changes", "extra_target_occurrences")}
    rows = []
    for case_id, case in sources.items():
        label, result = annotations[case_id], predictions[case_id]
        if label["source_image_sha256"] != case["images"]["400"]["sha256"]:
            raise ValueError("Label source image differs from the crop manifest")
        if result["saved_primary"] != case["text_before"]:
            raise ValueError("Retry original text differs from the saved primary")
        retry = result["retry"][str(dpi)]
        block, record = retry["block"], retry["record"]
        if (block["text_raw"] != case["text_before"] or block["bbox"] != case["bbox"]
                or block.get("source_id") != case["source_id"]):
            raise ValueError("Retry erased source evidence")
        counts["attempted"] += record["attempted"]
        counts["applied"] += record.get("improved", record.get("applied", 0))
        counts["numeric_changes"] += not preserves_numeric_evidence(case["text_before"], retry["text_after"])
        if label["status"] != "AI_PRELIMINARY_TARGET_ONLY":
            counts["label_unresolved"] += 1
            rows.append({"case_id": case_id, "effect": "NOT_EVALUATED"})
            continue
        phrase, expected = label["target"], label["expected_occurrences"]
        if not isinstance(phrase, str) or not phrase.strip() or type(expected) is not int or expected < 1:
            raise ValueError("A target needs non-empty text and positive occurrence count")
        before = _literal_count(case["text_before"], phrase)
        after = _literal_count(retry["text_after"], phrase)
        before_ok, after_ok = before == expected, after == expected
        effect = ("preserved_correct" if after_ok else "harmed") if before_ok else ("fixed" if after_ok else "still_wrong")
        counts["eligible"] += 1
        counts["before_correct" if before_ok else "before_wrong"] += 1
        counts[effect] += 1
        counts["extra_target_occurrences"] += max(0, after-expected)
        rows.append({"case_id": case_id, "effect": effect, "target": phrase, "expected": expected,
                     "before_occurrences": before, "after_occurrences": after,
                     "text_before": case["text_before"], "text_after": retry["text_after"]})
    return {"status": "DIAGNOSTIC_AI_LABELS_ONLY", "acceptance": "NOT_EVALUATED", "dpi": dpi,
            "scope": "Per-crop replay of saved primary; target phrases only; page budget not evaluated",
            "counts": counts,
            "fix_rate_given_before_wrong": counts["fixed"]/counts["before_wrong"] if counts["before_wrong"] else None,
            "harm_rate_given_before_correct": counts["harmed"]/counts["before_correct"] if counts["before_correct"] else None,
            "whole_line_accuracy": None, "rows": rows}
